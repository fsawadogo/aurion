import Foundation
import UIKit
import Vision
import CoreImage

// MARK: - Masking Result

/// Reason a masking operation failed. Distinguishes operational failures
/// (detection threw, render produced nil) from a successful pass that simply
/// found nothing to mask. Used by the audit log and by SessionManager when
/// deciding whether to offer the clinician a retry.
enum MaskingFailureReason: String {
    case invalidImage = "invalid_image"
    case detectionError = "detection_error"
    case ocrError = "ocr_error"
    case renderError = "render_error"
}

/// Frame type carried alongside the masking result so callers and the
/// audit log can attribute a failure to the right pipeline.
enum MaskingFrameType: String {
    case video
    case screen
}

/// Result of a masking or redaction operation.
///
/// `imageData` is non-nil only when masking completed successfully. If
/// `failureReason` is set, callers MUST NOT upload the image — the
/// pipeline is fail-closed per P0-01.
struct MaskingResult {
    let imageData: Data?
    let success: Bool
    let frameType: MaskingFrameType
    let facesDetected: Int
    let phiRegionsRedacted: Int
    let failureReason: MaskingFailureReason?
    let failureMessage: String?

    init(
        imageData: Data?,
        success: Bool,
        frameType: MaskingFrameType,
        facesDetected: Int = 0,
        phiRegionsRedacted: Int = 0,
        failureReason: MaskingFailureReason? = nil,
        failureMessage: String? = nil
    ) {
        self.imageData = imageData
        self.success = success
        self.frameType = frameType
        self.facesDetected = facesDetected
        self.phiRegionsRedacted = phiRegionsRedacted
        self.failureReason = failureReason
        self.failureMessage = failureMessage
    }
}

// MARK: - Masking Pipeline

/// On-device PHI masking pipeline.
/// Video frames: Apple Vision face detection + Gaussian blur.
/// Screen frames: Apple Vision OCR + PHI pattern redaction.
/// Masking status written to audit log BEFORE any S3 upload.
final class MaskingPipeline {
    static let shared = MaskingPipeline()

    /// Gaussian blur radius applied to detected face regions.
    private let faceBlurRadius: CGFloat = 30.0

    /// JPEG compression quality for output images.
    private let outputCompressionQuality: CGFloat = 0.85

    /// Core Image context — reused across calls for performance.
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    private init() {}

    // MARK: - Video Frame Masking (Face Detection + Blur)

    /// Mask faces in a video frame using Apple Vision face detection and Gaussian blur.
    /// Returns the masked image data and masking metadata.
    /// Logs `masking_confirmed` audit event with `faces_detected` count BEFORE any upload.
    func maskVideoFrame(_ image: UIImage, sessionId: String) async -> MaskingResult {
        guard let cgImage = image.cgImage else {
            AuditLogger.log(
                event: .maskingFailed,
                sessionId: sessionId,
                extra: [
                    "frame_type": MaskingFrameType.video.rawValue,
                    "failure_reason": MaskingFailureReason.invalidImage.rawValue,
                ]
            )
            return MaskingResult(
                imageData: nil,
                success: false,
                frameType: .video,
                failureReason: .invalidImage
            )
        }

        // Detect face bounding boxes using Vision framework.
        // Fail-closed: if detection throws, we drop the frame entirely. The
        // alternative — uploading the original image — would leak unmasked
        // PHI and violates CLAUDE.md §"Non-Negotiable Technical Rules".
        let faceRects: [CGRect]
        do {
            faceRects = try await detectFaces(in: cgImage)
        } catch {
            AuditLogger.log(
                event: .maskingFailed,
                sessionId: sessionId,
                extra: [
                    "frame_type": MaskingFrameType.video.rawValue,
                    "failure_reason": MaskingFailureReason.detectionError.rawValue,
                    "detection_error": error.localizedDescription,
                ]
            )
            return MaskingResult(
                imageData: nil,
                success: false,
                frameType: .video,
                failureReason: .detectionError,
                failureMessage: error.localizedDescription
            )
        }

        // No faces detected — the frame is genuinely clean, so we return the
        // original. This is the only path where the original bytes leave the
        // pipeline, and only after a successful Vision pass confirmed nothing
        // to mask.
        if faceRects.isEmpty {
            let data = image.jpegData(compressionQuality: outputCompressionQuality)
            guard let data else {
                AuditLogger.log(
                    event: .maskingFailed,
                    sessionId: sessionId,
                    extra: [
                        "frame_type": MaskingFrameType.video.rawValue,
                        "failure_reason": MaskingFailureReason.renderError.rawValue,
                    ]
                )
                return MaskingResult(
                    imageData: nil,
                    success: false,
                    frameType: .video,
                    failureReason: .renderError
                )
            }
            AuditLogger.log(
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: ["frame_type": MaskingFrameType.video.rawValue, "faces_detected": "0"]
            )
            return MaskingResult(imageData: data, success: true, frameType: .video)
        }

        // Apply Gaussian blur to each detected face region. Render failure is
        // treated as a masking failure — never fall back to the unblurred image.
        let maskedData = applyFaceBlur(
            to: cgImage,
            faceRects: faceRects,
            originalOrientation: image.imageOrientation
        )

        guard let maskedData else {
            AuditLogger.log(
                event: .maskingFailed,
                sessionId: sessionId,
                extra: [
                    "frame_type": MaskingFrameType.video.rawValue,
                    "failure_reason": MaskingFailureReason.renderError.rawValue,
                    "faces_detected": "\(faceRects.count)",
                ]
            )
            return MaskingResult(
                imageData: nil,
                success: false,
                frameType: .video,
                facesDetected: faceRects.count,
                failureReason: .renderError
            )
        }

        AuditLogger.log(
            event: .maskingConfirmed,
            sessionId: sessionId,
            extra: ["frame_type": MaskingFrameType.video.rawValue, "faces_detected": "\(faceRects.count)"]
        )

        return MaskingResult(
            imageData: maskedData,
            success: true,
            frameType: .video,
            facesDetected: faceRects.count
        )
    }

    // MARK: - Screen PHI Redaction (OCR + Pattern Matching)

    /// Redact PHI from a screen capture using Apple Vision OCR and pattern matching.
    /// Checks recognized text against patient name, MRN, DOB, and health card patterns.
    /// Fills matched bounding boxes with solid black rectangles.
    /// Logs `masking_confirmed` audit event with `phi_regions_redacted` count.
    func redactScreenCapture(_ image: UIImage, sessionId: String) async -> MaskingResult {
        guard let cgImage = image.cgImage else {
            AuditLogger.log(
                event: .maskingFailed,
                sessionId: sessionId,
                extra: [
                    "frame_type": MaskingFrameType.screen.rawValue,
                    "failure_reason": MaskingFailureReason.invalidImage.rawValue,
                ]
            )
            return MaskingResult(
                imageData: nil,
                success: false,
                frameType: .screen,
                failureReason: .invalidImage
            )
        }

        // Run OCR to get text observations with bounding boxes.
        // Fail-closed on OCR failure — without OCR we cannot prove the screen
        // is clean, so the safe action is to drop the frame.
        let textObservations: [VNRecognizedTextObservation]
        do {
            textObservations = try await recognizeText(in: cgImage)
        } catch {
            AuditLogger.log(
                event: .maskingFailed,
                sessionId: sessionId,
                extra: [
                    "frame_type": MaskingFrameType.screen.rawValue,
                    "failure_reason": MaskingFailureReason.ocrError.rawValue,
                    "ocr_error": error.localizedDescription,
                ]
            )
            return MaskingResult(
                imageData: nil,
                success: false,
                frameType: .screen,
                failureReason: .ocrError,
                failureMessage: error.localizedDescription
            )
        }

        // Identify PHI regions by checking each text observation against patterns
        let imageWidth = CGFloat(cgImage.width)
        let imageHeight = CGFloat(cgImage.height)
        var phiRects: [CGRect] = []

        for observation in textObservations {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let text = candidate.string

            if Self.containsPHIPattern(text) {
                // Vision normalized coordinates: origin at bottom-left, values 0..1.
                // Convert to pixel coordinates with origin at top-left for Core Graphics.
                let normalizedBox = observation.boundingBox
                let pixelRect = CGRect(
                    x: normalizedBox.origin.x * imageWidth,
                    y: (1.0 - normalizedBox.origin.y - normalizedBox.height) * imageHeight,
                    width: normalizedBox.width * imageWidth,
                    height: normalizedBox.height * imageHeight
                )
                // Expand slightly for better coverage
                let padded = pixelRect.insetBy(dx: -4, dy: -4)
                phiRects.append(padded)
            }
        }

        // No PHI found — OCR ran and found nothing matching the PHI patterns,
        // so the original image is safe to forward. Render failure on the
        // straight-through JPEG re-encode is still treated as fail-closed.
        if phiRects.isEmpty {
            guard let data = image.jpegData(compressionQuality: outputCompressionQuality) else {
                AuditLogger.log(
                    event: .maskingFailed,
                    sessionId: sessionId,
                    extra: [
                        "frame_type": MaskingFrameType.screen.rawValue,
                        "failure_reason": MaskingFailureReason.renderError.rawValue,
                    ]
                )
                return MaskingResult(
                    imageData: nil,
                    success: false,
                    frameType: .screen,
                    failureReason: .renderError
                )
            }
            AuditLogger.log(
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: ["frame_type": MaskingFrameType.screen.rawValue, "phi_regions_redacted": "0"]
            )
            return MaskingResult(imageData: data, success: true, frameType: .screen)
        }

        // Draw black rectangles over PHI regions. Render failure here is
        // explicitly fail-closed — we never forward a frame whose redaction
        // attempt produced no bytes.
        guard let redactedData = applyBlackRedaction(
            to: cgImage,
            rects: phiRects,
            originalOrientation: image.imageOrientation
        ) else {
            AuditLogger.log(
                event: .maskingFailed,
                sessionId: sessionId,
                extra: [
                    "frame_type": MaskingFrameType.screen.rawValue,
                    "failure_reason": MaskingFailureReason.renderError.rawValue,
                    "phi_regions_redacted": "\(phiRects.count)",
                ]
            )
            return MaskingResult(
                imageData: nil,
                success: false,
                frameType: .screen,
                phiRegionsRedacted: phiRects.count,
                failureReason: .renderError
            )
        }

        AuditLogger.log(
            event: .maskingConfirmed,
            sessionId: sessionId,
            extra: ["frame_type": MaskingFrameType.screen.rawValue, "phi_regions_redacted": "\(phiRects.count)"]
        )

        return MaskingResult(
            imageData: redactedData,
            success: true,
            frameType: .screen,
            phiRegionsRedacted: phiRects.count
        )
    }

    // MARK: - Vision Face Detection

    /// Detect face bounding boxes using VNDetectFaceRectanglesRequest (iOS 16+).
    /// Returns an array of face rectangles in normalized Vision coordinates.
    private func detectFaces(in cgImage: CGImage) async throws -> [CGRect] {
        try await withCheckedThrowingContinuation { continuation in
            let request = VNDetectFaceRectanglesRequest { request, error in
                if let error = error {
                    continuation.resume(throwing: error)
                    return
                }
                let faceObservations = request.results as? [VNFaceObservation] ?? []
                let rects = faceObservations.map { $0.boundingBox }
                continuation.resume(returning: rects)
            }
            // Prefer accuracy — clinical context requires reliable detection
            request.revision = VNDetectFaceRectanglesRequestRevision3

            let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
            do {
                try handler.perform([request])
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }

    // MARK: - Face Blur Application

    /// Apply Gaussian blur to face regions using Core Image.
    /// Each detected face bounding box is blurred with configurable radius.
    private func applyFaceBlur(to cgImage: CGImage, faceRects: [CGRect], originalOrientation: UIImage.Orientation) -> Data? {
        let imageWidth = CGFloat(cgImage.width)
        let imageHeight = CGFloat(cgImage.height)

        // Start with the original CIImage
        var outputImage = CIImage(cgImage: cgImage)

        for normalizedRect in faceRects {
            // Convert normalized Vision coordinates (bottom-left origin) to Core Image pixel coordinates.
            // Core Image also uses bottom-left origin, so we only need to scale.
            let pixelRect = CGRect(
                x: normalizedRect.origin.x * imageWidth,
                y: normalizedRect.origin.y * imageHeight,
                width: normalizedRect.width * imageWidth,
                height: normalizedRect.height * imageHeight
            )
            // Expand the rect slightly to ensure full face coverage
            let expandedRect = pixelRect.insetBy(dx: -pixelRect.width * 0.15, dy: -pixelRect.height * 0.15)

            // Create a blurred version of the entire image
            guard let blurFilter = CIFilter(name: "CIGaussianBlur") else { continue }
            blurFilter.setValue(outputImage, forKey: kCIInputImageKey)
            blurFilter.setValue(faceBlurRadius, forKey: kCIInputRadiusKey)
            guard let blurredImage = blurFilter.outputImage else { continue }

            // Crop the blurred image to just the face region, then composite it over the original.
            // CICrop clips the blurred result to the face rectangle.
            let croppedBlur = blurredImage.cropped(to: expandedRect)

            // Composite the blurred face region over the current output
            guard let compositeFilter = CIFilter(name: "CISourceOverCompositing") else { continue }
            compositeFilter.setValue(croppedBlur, forKey: kCIInputImageKey)
            compositeFilter.setValue(outputImage, forKey: kCIInputBackgroundImageKey)
            guard let composited = compositeFilter.outputImage else { continue }

            outputImage = composited
        }

        // Render the final composited image
        let renderExtent = CGRect(x: 0, y: 0, width: imageWidth, height: imageHeight)
        guard let finalCGImage = ciContext.createCGImage(outputImage, from: renderExtent) else {
            return nil
        }
        let finalUIImage = UIImage(cgImage: finalCGImage, scale: 1.0, orientation: originalOrientation)
        return finalUIImage.jpegData(compressionQuality: outputCompressionQuality)
    }

    // MARK: - Vision Text Recognition

    /// Run OCR on the image using VNRecognizeTextRequest.
    private func recognizeText(in cgImage: CGImage) async throws -> [VNRecognizedTextObservation] {
        try await withCheckedThrowingContinuation { continuation in
            let request = VNRecognizeTextRequest { request, error in
                if let error = error {
                    continuation.resume(throwing: error)
                    return
                }
                let observations = request.results as? [VNRecognizedTextObservation] ?? []
                continuation.resume(returning: observations)
            }
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true

            let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
            do {
                try handler.perform([request])
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }

    // MARK: - PHI Pattern Detection

    /// PHI patterns matched against on-screen text. Loosely grouped into
    /// identifier numbers (MRN, RAMQ, OHIP, SIN, account), names/labels
    /// (Patient, Last/First Name, Dr.), demographics (DOB, sex, age),
    /// contact (phone, email, postal, address), and location (room/bed).
    ///
    /// Conservative bias — the cost of a false positive (redacting a
    /// non-PHI string) is far lower than a false negative (leaking PHI).
    /// PHI patterns matched against on-screen text. Ordered so identifier
    /// numbers (the most common high-signal EMR fields) check first and
    /// short-circuit before broader name/contact patterns. Conservative
    /// bias — a false positive (redacting non-PHI) is far cheaper than a
    /// false negative.
    static let phiPatterns: [(label: String, regex: NSRegularExpression)] = {
        let definitions: [(String, String)] = [
            // ── Identifier numbers (anchored — fast-fail) ────────────
            ("mrn", #"(?i)(MRN|Medical\s+Record(?:\s+Number)?|Chart\s*#?|Dossier)\s*:?\s*[A-Z0-9\-]{4,}"#),
            ("ramq", #"\b[A-Z]{4}\s?\d{4}\s?\d{4}\b"#),
            ("ohip", #"\b\d{4}[\s\-]?\d{3}[\s\-]?\d{3}\b"#),
            ("health_card_label", #"(?i)(Health\s+Card|Carte\s+Soleil|RAMQ|OHIP|NAM)\s*:?\s*[A-Z0-9\s\-]{8,}"#),
            ("sin", #"\b\d{3}[\s\-]?\d{3}[\s\-]?\d{3}\b"#),
            // Colon required — otherwise "Account Manager Smith" false-positives.
            ("account_number", #"(?i)(Account(?:\s*#)?|Visit(?:\s+Number)?|Encounter(?:\s+Number)?)\s*:\s*[A-Z0-9\-]{4,}"#),

            // ── Demographics ─────────────────────────────────────────
            ("dob", #"(?i)(DOB|Date\s+of\s+Birth|Birth\s*Date|Naissance|Born)\s*:?\s*\d{1,4}[\-/\.]\d{1,2}[\-/\.]\d{1,4}"#),
            ("age_label", #"(?i)Age\s*:\s*\d{1,3}\s*(y(?:ea)?r?s?|ans?)?"#),
            ("sex_label", #"(?i)(Sex|Gender|Sexe)\s*:\s*(M|F|Male|Female|Homme|Femme)\b"#),

            // ── Names ────────────────────────────────────────────────
            ("patient_name", #"(?i)(Patient|Name|Nom)\s*:\s*[A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+)+"#),
            ("last_first_name", #"(?i)(Last\s+Name|First\s+Name|Surname|Given\s+Name|Pr[éeè]nom)\s*:\s*[A-Z][a-zA-Z\-']+"#),
            ("clinician_name", #"(?i)(Dr\.?|Doctor|Physician|MD)\s+[A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+)?"#),
            // Broad — runs last because it false-positives on "Tenderness, Bilateral".
            // Worth the false positive: name-comma-name is a frequent EMR banner format.
            ("last_comma_first", #"\b[A-Z][a-zA-Z\-']+,\s*[A-Z][a-zA-Z\-']+\b"#),

            // ── Contact ──────────────────────────────────────────────
            ("phone", #"\b(?:\+?1[\s\-\.]?)?\(?[2-9]\d{2}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}\b"#),
            ("email", #"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"#),
            ("canadian_postal", #"\b[ABCEGHJKLMNPRSTVXY]\d[A-Z][\s\-]?\d[A-Z]\d\b"#),
            ("us_zip", #"\b\d{5}(?:\-\d{4})?\b"#),
            // English: number + name + suffix ("100 Sherbrooke Street").
            ("street_address_en", #"(?i)\b\d{1,5}\s+[A-Z][a-zA-Z\.\-]+\s+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?|Court|Ct\.?)\b"#),
            // French: number + type + name ("100 Rue Saint-Denis").
            ("street_address_fr", #"(?i)\b\d{1,5}\s+(?:Rue|Avenue|Av\.?|Boulevard|Boul\.?|Chemin|Place)\s+[A-Z][a-zA-Z\.\-']+(?:\s+[A-Z][a-zA-Z\.\-']+)?\b"#),

            // ── Location ─────────────────────────────────────────────
            ("room_bed", #"(?i)(Room|Bed|Chambre|Lit)\s*:?\s*[A-Z0-9\-]{1,8}"#),
        ]

        return definitions.compactMap { label, pattern in
            (try? NSRegularExpression(pattern: pattern, options: [])).map { (label, $0) }
        }
    }()

    /// Check whether a recognized text string matches any PHI pattern.
    /// Static because the matcher touches no instance state — callers in
    /// the OCR pipeline use it through `MaskingPipeline`, tests call it
    /// directly without the singleton.
    static func containsPHIPattern(_ text: String) -> Bool {
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        for (_, regex) in phiPatterns {
            if regex.firstMatch(in: text, options: [], range: range) != nil {
                return true
            }
        }
        return false
    }

    // MARK: - Black Redaction Drawing

    /// Draw solid black rectangles over the specified regions.
    private func applyBlackRedaction(to cgImage: CGImage, rects: [CGRect], originalOrientation: UIImage.Orientation) -> Data? {
        let width = cgImage.width
        let height = cgImage.height

        guard let colorSpace = cgImage.colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(
                  data: nil,
                  width: width,
                  height: height,
                  bitsPerComponent: cgImage.bitsPerComponent,
                  bytesPerRow: 0,
                  space: colorSpace,
                  bitmapInfo: cgImage.bitmapInfo.rawValue
              ) else {
            return nil
        }

        // Draw the original image
        let fullRect = CGRect(x: 0, y: 0, width: width, height: height)
        context.draw(cgImage, in: fullRect)

        // Core Graphics context has origin at bottom-left. The rects were already
        // converted to top-left origin pixel coordinates. Flip y for CG.
        context.setFillColor(UIColor.black.cgColor)
        for rect in rects {
            let cgRect = CGRect(
                x: rect.origin.x,
                y: CGFloat(height) - rect.origin.y - rect.height,
                width: rect.width,
                height: rect.height
            )
            context.fill(cgRect)
        }

        guard let resultImage = context.makeImage() else { return nil }
        let uiImage = UIImage(cgImage: resultImage, scale: 1.0, orientation: originalOrientation)
        return uiImage.jpegData(compressionQuality: outputCompressionQuality)
    }
}
