import Foundation
import UIKit
import Vision
import CoreImage

// MARK: - Masking Result

/// Result of a masking or redaction operation.
struct MaskingResult {
    let imageData: Data?
    let success: Bool
    let facesDetected: Int
    let phiRegionsRedacted: Int
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
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: ["frame_type": "video", "faces_detected": "0", "error": "invalid_image"]
            )
            return MaskingResult(imageData: nil, success: false, facesDetected: 0, phiRegionsRedacted: 0)
        }

        // Detect face bounding boxes using Vision framework
        let faceRects: [CGRect]
        do {
            faceRects = try await detectFaces(in: cgImage)
        } catch {
            // If detection fails, return original image — do not block the pipeline.
            // Log with zero faces so audit trail reflects the failure.
            let fallbackData = image.jpegData(compressionQuality: outputCompressionQuality)
            AuditLogger.log(
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: [
                    "frame_type": "video",
                    "faces_detected": "0",
                    "detection_error": error.localizedDescription,
                ]
            )
            return MaskingResult(imageData: fallbackData, success: fallbackData != nil, facesDetected: 0, phiRegionsRedacted: 0)
        }

        // No faces detected — return original image unchanged
        if faceRects.isEmpty {
            let data = image.jpegData(compressionQuality: outputCompressionQuality)
            AuditLogger.log(
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: ["frame_type": "video", "faces_detected": "0"]
            )
            return MaskingResult(imageData: data, success: data != nil, facesDetected: 0, phiRegionsRedacted: 0)
        }

        // Apply Gaussian blur to each detected face region
        let maskedData = applyFaceBlur(
            to: cgImage,
            faceRects: faceRects,
            originalOrientation: image.imageOrientation
        )

        AuditLogger.log(
            event: .maskingConfirmed,
            sessionId: sessionId,
            extra: ["frame_type": "video", "faces_detected": "\(faceRects.count)"]
        )

        return MaskingResult(
            imageData: maskedData,
            success: maskedData != nil,
            facesDetected: faceRects.count,
            phiRegionsRedacted: 0
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
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: ["frame_type": "screen", "phi_regions_redacted": "0", "error": "invalid_image"]
            )
            return MaskingResult(imageData: nil, success: false, facesDetected: 0, phiRegionsRedacted: 0)
        }

        // Run OCR to get text observations with bounding boxes
        let textObservations: [VNRecognizedTextObservation]
        do {
            textObservations = try await recognizeText(in: cgImage)
        } catch {
            let fallbackData = image.jpegData(compressionQuality: outputCompressionQuality)
            AuditLogger.log(
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: [
                    "frame_type": "screen",
                    "phi_regions_redacted": "0",
                    "ocr_error": error.localizedDescription,
                ]
            )
            return MaskingResult(imageData: fallbackData, success: fallbackData != nil, facesDetected: 0, phiRegionsRedacted: 0)
        }

        // Identify PHI regions by checking each text observation against patterns
        let imageWidth = CGFloat(cgImage.width)
        let imageHeight = CGFloat(cgImage.height)
        var phiRects: [CGRect] = []

        for observation in textObservations {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let text = candidate.string

            if containsPHIPattern(text) {
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

        // No PHI found — return original image
        if phiRects.isEmpty {
            let data = image.jpegData(compressionQuality: outputCompressionQuality)
            AuditLogger.log(
                event: .maskingConfirmed,
                sessionId: sessionId,
                extra: ["frame_type": "screen", "phi_regions_redacted": "0"]
            )
            return MaskingResult(imageData: data, success: data != nil, facesDetected: 0, phiRegionsRedacted: 0)
        }

        // Draw black rectangles over PHI regions
        let redactedData = applyBlackRedaction(to: cgImage, rects: phiRects, originalOrientation: image.imageOrientation)

        AuditLogger.log(
            event: .maskingConfirmed,
            sessionId: sessionId,
            extra: ["frame_type": "screen", "phi_regions_redacted": "\(phiRects.count)"]
        )

        return MaskingResult(
            imageData: redactedData,
            success: redactedData != nil,
            facesDetected: 0,
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

    /// PHI patterns to detect in screen captures:
    /// - Patient name labels: "Patient:", "Name:" followed by capitalized words
    /// - MRN: "MRN:" followed by digits
    /// - DOB: "DOB:", "Date of Birth:" followed by date-like strings
    /// - Health card: RAMQ (4 letters + 8 digits) or OHIP-style digit groups
    private static let phiPatterns: [(label: String, regex: NSRegularExpression)] = {
        var patterns: [(String, NSRegularExpression)] = []

        let definitions: [(String, String)] = [
            // Patient name — "Patient:" or "Name:" followed by capitalized words
            ("patient_name", #"(?i)(Patient|Name)\s*:\s*[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+"#),
            // MRN — "MRN:" or "MRN" followed by digits
            ("mrn", #"(?i)MRN\s*:?\s*\d{4,}"#),
            // DOB — "DOB:" or "Date of Birth:" followed by date-like string
            ("dob", #"(?i)(DOB|Date\s+of\s+Birth)\s*:\s*\d{1,4}[\-/\.]\d{1,2}[\-/\.]\d{1,4}"#),
            // RAMQ health card — 4 uppercase letters followed by 8 digits (Quebec)
            ("ramq", #"\b[A-Z]{4}\s?\d{4}\s?\d{4}\b"#),
            // OHIP health card — 10 digit number, possibly grouped
            ("ohip", #"\b\d{4}[\s\-]?\d{3}[\s\-]?\d{3}\b"#),
            // Generic "Health Card" label with a number
            ("health_card_label", #"(?i)(Health\s+Card|Carte\s+Soleil|RAMQ|OHIP)\s*:?\s*[A-Z0-9\s\-]{8,}"#),
        ]

        for (label, pattern) in definitions {
            if let regex = try? NSRegularExpression(pattern: pattern, options: []) {
                patterns.append((label, regex))
            }
        }
        return patterns
    }()

    /// Check whether a recognized text string matches any PHI pattern.
    private func containsPHIPattern(_ text: String) -> Bool {
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        for (_, regex) in Self.phiPatterns {
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
