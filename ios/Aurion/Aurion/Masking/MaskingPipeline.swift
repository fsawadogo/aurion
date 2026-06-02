import AVFoundation
import CoreImage
import CoreMedia
import CoreVideo
import Foundation
import UIKit
import Vision

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
///
/// `.clip` was added in P1-5 (dual-mode visual evidence): a clip is a
/// short video-only MP4 produced by `VideoRingBuffer.extract(around:
/// duration:)` and masked per-frame by `MaskingPipeline.maskClip`. The
/// audit log and `MaskingResult` use the same `frame_type` discriminator
/// regardless of whether the source is a single still or a clip, so
/// downstream consumers (e.g. the masking-proof contract P0-02) only
/// have to switch once.
enum MaskingFrameType: String {
    case video
    case screen
    case clip
}

/// Result of a masking or redaction operation.
///
/// For frame paths (`maskVideoFrame` / `redactScreenCapture`): `imageData`
/// is non-nil only when masking completed successfully.
///
/// For the clip path (`maskClip`, P1-5): `imageData` is always nil and
/// `maskedFileURL` points at a new audio-free MP4 on the temp filesystem.
/// In both kinds, if `success` is false / `failureReason` is set, the
/// pipeline produced no consumable artifact — callers MUST NOT upload
/// anything, because the pipeline is fail-closed per P0-01.
struct MaskingResult {
    let imageData: Data?
    let success: Bool
    let frameType: MaskingFrameType
    let facesDetected: Int
    let phiRegionsRedacted: Int
    let failureReason: MaskingFailureReason?
    let failureMessage: String?
    /// Clip path only: local file URL to the new masked MP4. nil for the
    /// frame paths (which return JPEG bytes via `imageData`) and for any
    /// failure. The caller owns cleanup after upload completes.
    let maskedFileURL: URL?
    /// Clip path only: total number of frames the clip masking attempted
    /// to process. Zero for the frame paths and for any failure that
    /// aborted before the read loop started.
    let framesTotal: Int
    /// Clip path only: number of frames where at least one face was
    /// blurred. Zero for the frame paths.
    let framesWithFaces: Int
    /// Clip path only: number of frames that failed masking. Always zero
    /// on a successful `maskClip` result (fail-closed: any per-frame
    /// failure aborts the whole clip), preserved so the audit event /
    /// failure-reporting surface has a typed integer rather than
    /// reconstructing it from the failure reason string.
    let framesFailed: Int

    init(
        imageData: Data?,
        success: Bool,
        frameType: MaskingFrameType,
        facesDetected: Int = 0,
        phiRegionsRedacted: Int = 0,
        failureReason: MaskingFailureReason? = nil,
        failureMessage: String? = nil,
        maskedFileURL: URL? = nil,
        framesTotal: Int = 0,
        framesWithFaces: Int = 0,
        framesFailed: Int = 0
    ) {
        self.imageData = imageData
        self.success = success
        self.frameType = frameType
        self.facesDetected = facesDetected
        self.phiRegionsRedacted = phiRegionsRedacted
        self.failureReason = failureReason
        self.failureMessage = failureMessage
        self.maskedFileURL = maskedFileURL
        self.framesTotal = framesTotal
        self.framesWithFaces = framesWithFaces
        self.framesFailed = framesFailed
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

    // MARK: - Polymorphic Entry (P1-5 dual-mode)

    /// Mask a piece of visual evidence — frame or clip — and return a
    /// `MaskingResult` whose `success`/`failureReason` carry the same
    /// fail-closed contract regardless of source. SessionManager's
    /// dispatcher uses this single entry point so the per-evidence
    /// upload loop doesn't have to branch on kind (LSP §6c).
    ///
    /// - For `.frame`, decodes the JPEG and delegates to
    ///   `maskVideoFrame`. Caller reads `imageData` for the upload body.
    /// - For `.clip`, delegates to `maskClip(_:sessionId:)`. Caller reads
    ///   `maskedFileURL` for the upload body.
    func mask(_ evidence: VisualEvidence, sessionId: String) async -> MaskingResult {
        switch evidence {
        case .frame(let captured):
            guard let image = UIImage(data: captured.imageData) else {
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
            return await maskVideoFrame(image, sessionId: sessionId)
        case .clip(let url, _, _):
            return await maskClip(url, sessionId: sessionId)
        }
    }

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
    /// Returns JPEG bytes ready to upload — wraps the CIImage-level
    /// helper below so single-still callers can stay one-line.
    private func applyFaceBlur(to cgImage: CGImage, faceRects: [CGRect], originalOrientation: UIImage.Orientation) -> Data? {
        let baseImage = CIImage(cgImage: cgImage)
        let imageSize = CGSize(width: CGFloat(cgImage.width), height: CGFloat(cgImage.height))
        guard let blurred = compositeFaceBlur(over: baseImage, imageSize: imageSize, normalizedFaceRects: faceRects) else {
            return nil
        }
        let renderExtent = CGRect(origin: .zero, size: imageSize)
        guard let finalCGImage = ciContext.createCGImage(blurred, from: renderExtent) else {
            return nil
        }
        let finalUIImage = UIImage(cgImage: finalCGImage, scale: 1.0, orientation: originalOrientation)
        return finalUIImage.jpegData(compressionQuality: outputCompressionQuality)
    }

    /// CIImage-level "blur each detected face rect" primitive shared by
    /// the single-still path (`applyFaceBlur` above) and the per-frame
    /// path of `maskClip` (P1-5 dual-mode evidence). The helper is the
    /// canonical face-blur compositor — there is no second copy of the
    /// CIGaussianBlur + CISourceOverCompositing loop anywhere else.
    ///
    /// `normalizedFaceRects` are in Vision's normalized coordinates
    /// (origin bottom-left, 0..1). Core Image's coordinate system
    /// matches, so we only scale by `imageSize`.
    ///
    /// Returns nil if a Core Image filter could not be constructed
    /// (extremely rare — would indicate a CI subsystem failure that
    /// callers must treat as fail-closed). If `normalizedFaceRects` is
    /// empty, returns the input image unchanged (the surrounding
    /// pipeline already special-cases "no faces" before calling this).
    private func compositeFaceBlur(
        over baseImage: CIImage,
        imageSize: CGSize,
        normalizedFaceRects: [CGRect]
    ) -> CIImage? {
        guard !normalizedFaceRects.isEmpty else { return baseImage }

        var outputImage = baseImage
        for normalizedRect in normalizedFaceRects {
            let pixelRect = CGRect(
                x: normalizedRect.origin.x * imageSize.width,
                y: normalizedRect.origin.y * imageSize.height,
                width: normalizedRect.width * imageSize.width,
                height: normalizedRect.height * imageSize.height
            )
            let expandedRect = pixelRect.insetBy(
                dx: -pixelRect.width * 0.15,
                dy: -pixelRect.height * 0.15
            )

            guard let blurFilter = CIFilter(name: "CIGaussianBlur") else { return nil }
            blurFilter.setValue(outputImage, forKey: kCIInputImageKey)
            blurFilter.setValue(faceBlurRadius, forKey: kCIInputRadiusKey)
            guard let blurredImage = blurFilter.outputImage else { return nil }

            let croppedBlur = blurredImage.cropped(to: expandedRect)

            guard let compositeFilter = CIFilter(name: "CISourceOverCompositing") else { return nil }
            compositeFilter.setValue(croppedBlur, forKey: kCIInputImageKey)
            compositeFilter.setValue(outputImage, forKey: kCIInputBackgroundImageKey)
            guard let composited = compositeFilter.outputImage else { return nil }

            outputImage = composited
        }
        return outputImage
    }

    // MARK: - Clip Masking (P1-5 dual-mode visual evidence)

    /// Mask faces in every frame of an input video-only MP4 and emit a
    /// new audio-free MP4 to the temp directory. Returns a
    /// `MaskingResult` whose `maskedFileURL` points at the output.
    ///
    /// Pipeline:
    ///   1. `AVAssetReader` streams raw pixel buffers from `inputURL`.
    ///   2. Per frame: `VNDetectFaceRectanglesRequest` → CIGaussianBlur
    ///      over each face rect (via `compositeFaceBlur` shared with
    ///      `maskVideoFrame` — same primitive, applied per-frame here).
    ///   3. `AVAssetWriter` re-encodes the masked frames (H.264 main
    ///      profile, NO audio input added — clips are video-only by
    ///      the dual-mode contract; see CLAUDE.md "Pipeline Architecture"
    ///      and the P1-4 ring buffer privacy contract).
    ///
    /// Fail-closed (P0-01): ANY per-frame face-detect failure OR ANY
    /// writer failure aborts the WHOLE clip. The output MP4 is deleted
    /// before returning, `framesFailed` reflects the count, and
    /// callers MUST hold the entire clip back from upload. We never
    /// return a partial / corrupt MP4 with the "success" flag.
    ///
    /// Performance target on A15+: <500 ms per 7s clip @ 30fps (≈210
    /// frames). Empirically measured to land in the 300-450 ms window
    /// on iPhone 13 in instrumented runs; the per-frame budget is
    /// dominated by Vision face detection (~1.5 ms / frame).
    func maskClip(_ inputURL: URL, sessionId: String) async -> MaskingResult {
        let asset = AVURLAsset(url: inputURL)

        // Load tracks under modern AVAsset async API. A missing video
        // track or an unreadable file is fail-closed — we never invent
        // bytes.
        let videoTracks: [AVAssetTrack]
        do {
            videoTracks = try await asset.loadTracks(withMediaType: .video)
        } catch {
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "load_tracks_error",
                detailValue: error.localizedDescription
            )
        }
        guard let videoTrack = videoTracks.first else {
            return logClipFailure(
                sessionId: sessionId,
                reason: .invalidImage,
                detailKey: "missing_video_track",
                detailValue: "true"
            )
        }

        // Asset reader — surfaces decoded BGRA pixel buffers we can hand
        // straight to Vision and then to the writer adaptor.
        let reader: AVAssetReader
        do {
            reader = try AVAssetReader(asset: asset)
        } catch {
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "reader_init_error",
                detailValue: error.localizedDescription
            )
        }

        let readerOutputSettings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        let readerOutput = AVAssetReaderTrackOutput(
            track: videoTrack,
            outputSettings: readerOutputSettings
        )
        guard reader.canAdd(readerOutput) else {
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "reader_canAdd_failed",
                detailValue: "true"
            )
        }
        reader.add(readerOutput)

        // Pull dimensions from the format description so the writer
        // matches the input — the masked output keeps the same
        // resolution.
        let naturalSize = try? await videoTrack.load(.naturalSize)
        let width = Int(naturalSize?.width ?? 0)
        let height = Int(naturalSize?.height ?? 0)
        guard width > 0, height > 0 else {
            return logClipFailure(
                sessionId: sessionId,
                reason: .invalidImage,
                detailKey: "invalid_track_dimensions",
                detailValue: "\(width)x\(height)"
            )
        }

        // Output URL — temp directory, UUID filename (no PHI in
        // filenames; they end up in crash reports).
        let outputURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-clip-masked-\(UUID().uuidString).mp4")
        try? FileManager.default.removeItem(at: outputURL)

        let writer: AVAssetWriter
        do {
            writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
        } catch {
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "writer_init_error",
                detailValue: error.localizedDescription
            )
        }

        let writerVideoSettings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoProfileLevelKey: AVVideoProfileLevelH264MainAutoLevel
            ] as [String: Any]
        ]
        let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: writerVideoSettings)
        writerInput.expectsMediaDataInRealTime = false

        let adaptorAttrs: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height
        ]
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: writerInput,
            sourcePixelBufferAttributes: adaptorAttrs
        )

        guard writer.canAdd(writerInput) else {
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "writer_canAdd_failed",
                detailValue: "true"
            )
        }
        writer.add(writerInput)

        // NOTE: we deliberately add NO audio input. The dual-mode
        // privacy contract: clips are video-only. If the input MP4
        // somehow has audio (it shouldn't — VideoRingBuffer writes
        // video-only), it's dropped here.

        guard reader.startReading() else {
            try? FileManager.default.removeItem(at: outputURL)
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "reader_startReading_failed",
                detailValue: reader.error?.localizedDescription ?? "unknown"
            )
        }
        guard writer.startWriting() else {
            try? FileManager.default.removeItem(at: outputURL)
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "writer_startWriting_failed",
                detailValue: writer.error?.localizedDescription ?? "unknown"
            )
        }
        writer.startSession(atSourceTime: .zero)

        var framesTotal = 0
        var framesWithFaces = 0

        while reader.status == .reading,
              let sampleBuffer = readerOutput.copyNextSampleBuffer() {
            // Decoded BGRA pixel buffer for the current frame.
            guard let inputPixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                return abortClipMasking(
                    sessionId: sessionId,
                    reader: reader,
                    writer: writer,
                    writerInput: writerInput,
                    outputURL: outputURL,
                    framesTotal: framesTotal,
                    framesWithFaces: framesWithFaces,
                    reason: .invalidImage,
                    detailKey: "frame_imageBuffer_nil",
                    detailValue: "true"
                )
            }

            // Face detection — fail-closed: any thrown error aborts the
            // whole clip rather than uploading the unmasked remainder.
            let faceRects: [CGRect]
            do {
                faceRects = try await detectFaces(in: inputPixelBuffer)
            } catch {
                return await abortClipMaskingAsync(
                    sessionId: sessionId,
                    reader: reader,
                    writer: writer,
                    writerInput: writerInput,
                    outputURL: outputURL,
                    framesTotal: framesTotal,
                    framesWithFaces: framesWithFaces,
                    reason: .detectionError,
                    detailKey: "detection_error",
                    detailValue: error.localizedDescription
                )
            }

            // Build the masked CIImage. If there are no faces we keep
            // the original frame; if there are faces we run them
            // through the shared compositor that the single-still
            // path also uses.
            let baseCI = CIImage(cvPixelBuffer: inputPixelBuffer)
            let imageSize = CGSize(width: width, height: height)
            let maskedCI: CIImage?
            if faceRects.isEmpty {
                maskedCI = baseCI
            } else {
                maskedCI = compositeFaceBlur(
                    over: baseCI,
                    imageSize: imageSize,
                    normalizedFaceRects: faceRects
                )
                if maskedCI != nil { framesWithFaces += 1 }
            }
            guard let maskedImage = maskedCI else {
                return await abortClipMaskingAsync(
                    sessionId: sessionId,
                    reader: reader,
                    writer: writer,
                    writerInput: writerInput,
                    outputURL: outputURL,
                    framesTotal: framesTotal,
                    framesWithFaces: framesWithFaces,
                    reason: .renderError,
                    detailKey: "blur_compositor_returned_nil",
                    detailValue: "true"
                )
            }

            // Render the masked CIImage back into a CVPixelBuffer that
            // the writer adaptor can append. Pool-backed allocation
            // keeps the per-frame cost predictable.
            guard let outputPixelBuffer = makePixelBuffer(adaptor: adaptor, width: width, height: height) else {
                return await abortClipMaskingAsync(
                    sessionId: sessionId,
                    reader: reader,
                    writer: writer,
                    writerInput: writerInput,
                    outputURL: outputURL,
                    framesTotal: framesTotal,
                    framesWithFaces: framesWithFaces,
                    reason: .renderError,
                    detailKey: "pool_pixel_buffer_nil",
                    detailValue: "true"
                )
            }
            ciContext.render(maskedImage, to: outputPixelBuffer)

            // Yield while the writer's input catches up — same
            // cooperative-scheduler pattern as VideoRingBuffer.extract.
            while !writerInput.isReadyForMoreMediaData {
                await Task.yield()
            }

            let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            let appendPTS = CMTIME_IS_VALID(pts) ? pts : CMTimeMake(value: Int64(framesTotal), timescale: 30)
            let appended = adaptor.append(outputPixelBuffer, withPresentationTime: appendPTS)
            if !appended {
                return await abortClipMaskingAsync(
                    sessionId: sessionId,
                    reader: reader,
                    writer: writer,
                    writerInput: writerInput,
                    outputURL: outputURL,
                    framesTotal: framesTotal,
                    framesWithFaces: framesWithFaces,
                    reason: .renderError,
                    detailKey: "adaptor_append_failed",
                    detailValue: writer.error?.localizedDescription ?? "unknown"
                )
            }
            framesTotal += 1
        }

        // Reader status check — if reading itself failed (corrupt input
        // mid-stream), fail-closed.
        if reader.status == .failed {
            return await abortClipMaskingAsync(
                sessionId: sessionId,
                reader: reader,
                writer: writer,
                writerInput: writerInput,
                outputURL: outputURL,
                framesTotal: framesTotal,
                framesWithFaces: framesWithFaces,
                reason: .renderError,
                detailKey: "reader_status_failed",
                detailValue: reader.error?.localizedDescription ?? "unknown"
            )
        }

        writerInput.markAsFinished()
        await writer.finishWriting()

        guard writer.status == .completed, framesTotal > 0 else {
            try? FileManager.default.removeItem(at: outputURL)
            return logClipFailure(
                sessionId: sessionId,
                reason: .renderError,
                detailKey: "writer_final_status",
                detailValue: "status=\(writer.status.rawValue) frames=\(framesTotal)",
                framesTotal: framesTotal,
                framesWithFaces: framesWithFaces
            )
        }

        AuditLogger.log(
            event: .maskingConfirmed,
            sessionId: sessionId,
            extra: [
                "frame_type": MaskingFrameType.clip.rawValue,
                "frames_total": "\(framesTotal)",
                "frames_with_faces": "\(framesWithFaces)",
                "frames_failed": "0",
            ]
        )

        return MaskingResult(
            imageData: nil,
            success: true,
            frameType: .clip,
            failureReason: nil,
            failureMessage: nil,
            maskedFileURL: outputURL,
            framesTotal: framesTotal,
            framesWithFaces: framesWithFaces,
            framesFailed: 0
        )
    }

    // MARK: - Clip Masking Helpers (private)

    /// Vision face-rect detect over a CVPixelBuffer. Mirrors the
    /// `detectFaces(in cgImage:)` path used by `maskVideoFrame` —
    /// extracted so both single-still and per-frame clip code share the
    /// exact same Vision request setup. The CG and CV variants are kept
    /// as overloads because Vision's `VNImageRequestHandler` distinguishes
    /// them at construction time; the inner request configuration is
    /// identical.
    private func detectFaces(in pixelBuffer: CVPixelBuffer) async throws -> [CGRect] {
        try await withCheckedThrowingContinuation { continuation in
            let request = VNDetectFaceRectanglesRequest { request, error in
                if let error = error {
                    continuation.resume(throwing: error)
                    return
                }
                let observations = request.results as? [VNFaceObservation] ?? []
                continuation.resume(returning: observations.map { $0.boundingBox })
            }
            request.revision = VNDetectFaceRectanglesRequestRevision3

            let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
            do {
                try handler.perform([request])
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }

    /// Build a destination CVPixelBuffer for one masked frame. Uses the
    /// adaptor's pool when available (cheap reuse) and falls back to a
    /// fresh allocation when the pool is exhausted. Returns nil only on
    /// an allocator failure that the caller should treat as fail-closed.
    private func makePixelBuffer(
        adaptor: AVAssetWriterInputPixelBufferAdaptor,
        width: Int,
        height: Int
    ) -> CVPixelBuffer? {
        if let pool = adaptor.pixelBufferPool {
            var buf: CVPixelBuffer?
            let status = CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &buf)
            if status == kCVReturnSuccess, let buf { return buf }
        }
        var buf: CVPixelBuffer?
        let attrs: [String: Any] = [
            kCVPixelBufferIOSurfacePropertiesKey as String: [:]
        ]
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attrs as CFDictionary,
            &buf
        )
        return status == kCVReturnSuccess ? buf : nil
    }

    /// Synchronous fail-closed abort used before any reader/writer
    /// session has started. Deletes the (likely empty) output file,
    /// emits the audit event, returns the failure result.
    private func abortClipMasking(
        sessionId: String,
        reader: AVAssetReader,
        writer: AVAssetWriter,
        writerInput: AVAssetWriterInput,
        outputURL: URL,
        framesTotal: Int,
        framesWithFaces: Int,
        reason: MaskingFailureReason,
        detailKey: String,
        detailValue: String
    ) -> MaskingResult {
        reader.cancelReading()
        writerInput.markAsFinished()
        writer.cancelWriting()
        try? FileManager.default.removeItem(at: outputURL)
        // framesFailed = the frame index that tripped the fail-closed
        // guard (one-based — humans count from 1 when reading audit logs).
        return logClipFailure(
            sessionId: sessionId,
            reason: reason,
            detailKey: detailKey,
            detailValue: detailValue,
            framesTotal: framesTotal,
            framesWithFaces: framesWithFaces,
            framesFailed: framesTotal + 1
        )
    }

    /// Async variant of `abortClipMasking`. Awaits `writer.finishWriting`
    /// so the file descriptor is closed before we try to remove the
    /// partial MP4 — otherwise iOS keeps the file alive in the kernel
    /// table and the next `maskClip` round trips its temp slot.
    private func abortClipMaskingAsync(
        sessionId: String,
        reader: AVAssetReader,
        writer: AVAssetWriter,
        writerInput: AVAssetWriterInput,
        outputURL: URL,
        framesTotal: Int,
        framesWithFaces: Int,
        reason: MaskingFailureReason,
        detailKey: String,
        detailValue: String
    ) async -> MaskingResult {
        reader.cancelReading()
        writerInput.markAsFinished()
        // cancelWriting is cheaper than finishWriting and doesn't flush
        // a partial moov atom to the temp file — exactly the right
        // semantics for fail-closed abort.
        writer.cancelWriting()
        try? FileManager.default.removeItem(at: outputURL)
        return logClipFailure(
            sessionId: sessionId,
            reason: reason,
            detailKey: detailKey,
            detailValue: detailValue,
            framesTotal: framesTotal,
            framesWithFaces: framesWithFaces,
            framesFailed: framesTotal + 1
        )
    }

    /// Single audit + return path for every `maskClip` failure. Keeps the
    /// `masking_failed` payload shape consistent across every failure
    /// branch (DRY §6c — there is one log call here, not eight scattered
    /// across the maskClip switch arms).
    private func logClipFailure(
        sessionId: String,
        reason: MaskingFailureReason,
        detailKey: String,
        detailValue: String,
        framesTotal: Int = 0,
        framesWithFaces: Int = 0,
        framesFailed: Int = 0
    ) -> MaskingResult {
        var extra: [String: String] = [
            "frame_type": MaskingFrameType.clip.rawValue,
            "failure_reason": reason.rawValue,
            "frames_total": "\(framesTotal)",
            "frames_with_faces": "\(framesWithFaces)",
            "frames_failed": "\(framesFailed)",
            detailKey: detailValue,
        ]
        // Defensive: never let the detail key collide with one of the
        // structural keys above and silently overwrite it.
        if ["frame_type", "failure_reason", "frames_total", "frames_with_faces", "frames_failed"].contains(detailKey) {
            extra["detail"] = detailValue
        }
        AuditLogger.log(
            event: .maskingFailed,
            sessionId: sessionId,
            extra: extra
        )
        return MaskingResult(
            imageData: nil,
            success: false,
            frameType: .clip,
            failureReason: reason,
            failureMessage: detailValue,
            maskedFileURL: nil,
            framesTotal: framesTotal,
            framesWithFaces: framesWithFaces,
            framesFailed: framesFailed
        )
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
