import ReplayKit
import Combine
import UIKit
import CoreMedia

// MARK: - Screen Capture Manager

/// Captures screen content for lab/imaging review detection using ReplayKit.
///
/// Screen frames are processed through the screen capture pipeline:
/// 1. PHI redaction on-device (via MaskingPipeline)
/// 2. Screen type classification (lab_result, imaging_viewer, emr, other)
/// 3. OCR extraction (AWS Textract or local mode)
/// 4. Timestamp anchoring to transcript segments
/// 5. Note injection into the appropriate section
///
/// This manager captures screen frames at a configurable FPS (default 2 from
/// AppConfig `pipeline.screen_capture_fps`) and stores them as `CapturedFrame`
/// objects with JPEG data at 0.85 quality.
///
/// Toggled via AppConfig `feature_flags.screen_capture_enabled`.
@MainActor
final class ScreenCaptureManager: ObservableObject {

    // MARK: - Published State

    @Published var isRecording = false
    @Published var capturedScreenFrames: [CapturedFrame] = []
    @Published var error: String?

    // MARK: - Configuration

    /// JPEG compression quality for screen captures.
    private let jpegQuality: CGFloat = 0.85

    // MARK: - Internal State

    /// The configured frames-per-second rate for screen capture.
    private nonisolated(unsafe) var targetFPS: Int = 2

    /// Timestamp of the last captured frame, used to throttle to the target FPS.
    private nonisolated(unsafe) var lastCaptureTime: TimeInterval = 0

    /// Session start time for computing relative timestamps.
    private nonisolated(unsafe) var sessionStartTime: TimeInterval = 0

    /// Reference to the shared screen recorder.
    private var recorder: RPScreenRecorder {
        RPScreenRecorder.shared()
    }

    // MARK: - Capture Control

    /// Starts capturing screen content at the specified FPS.
    ///
    /// - Parameter fps: Frames per second to capture. Default is 2 (from AppConfig
    ///   `pipeline.screen_capture_fps`). Higher values increase storage and processing cost.
    func startCapture(fps: Int = 2) {
        guard !isRecording else { return }
        guard recorder.isAvailable else {
            error = "Screen recording is not available on this device."
            return
        }

        targetFPS = max(1, fps)
        capturedScreenFrames = []
        lastCaptureTime = 0
        sessionStartTime = Date.timeIntervalSinceReferenceDate
        error = nil

        recorder.startCapture(handler: { [weak self] sampleBuffer, sampleBufferType, captureError in
            // This handler is called on an arbitrary queue
            if let captureError {
                Task { @MainActor [weak self] in
                    self?.error = "Screen capture error: \(captureError.localizedDescription)"
                }
                return
            }

            // We only care about video frames, not audio or microphone buffers
            guard sampleBufferType == .video else { return }

            self?.handleScreenSampleBuffer(sampleBuffer)

        }, completionHandler: { [weak self] captureError in
            Task { @MainActor [weak self] in
                if let captureError {
                    self?.error = "Failed to start screen capture: \(captureError.localizedDescription)"
                    self?.isRecording = false
                } else {
                    self?.isRecording = true
                }
            }
        })
    }

    /// Stops screen capture.
    func stopCapture() {
        guard isRecording else { return }

        recorder.stopCapture { [weak self] captureError in
            Task { @MainActor [weak self] in
                self?.isRecording = false
                if let captureError {
                    self?.error = "Failed to stop screen capture: \(captureError.localizedDescription)"
                }
            }
        }
    }

    // MARK: - Sample Buffer Processing

    /// Handles a video sample buffer from RPScreenRecorder, throttling to the target FPS.
    private nonisolated func handleScreenSampleBuffer(_ sampleBuffer: CMSampleBuffer) {
        let now = Date.timeIntervalSinceReferenceDate
        let interval = 1.0 / Double(targetFPS)

        // Throttle: skip frames that arrive faster than the target interval
        guard now - lastCaptureTime >= interval else { return }
        lastCaptureTime = now

        // Convert CMSampleBuffer to UIImage then to JPEG data
        guard let imageData = convertSampleBufferToJPEG(sampleBuffer) else { return }

        let relativeTimestamp = now - sessionStartTime
        let frame = CapturedFrame(timestamp: relativeTimestamp, imageData: imageData)

        Task { @MainActor [weak self] in
            guard let self, self.isRecording else { return }
            self.capturedScreenFrames.append(frame)
        }
    }

    /// Converts a CMSampleBuffer (from RPScreenRecorder) to JPEG Data.
    private nonisolated func convertSampleBufferToJPEG(_ sampleBuffer: CMSampleBuffer) -> Data? {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return nil }

        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return nil }

        let uiImage = UIImage(cgImage: cgImage)
        return uiImage.jpegData(compressionQuality: jpegQuality)
    }
}
