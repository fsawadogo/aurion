import AVFoundation
import Combine
import UIKit

// MARK: - Captured Frame Model

/// A single captured video frame with timestamp and JPEG data.
struct CapturedFrame: Identifiable {
    let id = UUID()
    let timestamp: TimeInterval
    let imageData: Data
}

// MARK: - Permission State

enum CapturePermissionStatus {
    case notDetermined
    case authorized
    case denied
}

// MARK: - Capture Manager

/// Manages real audio + video capture sessions using AVFoundation.
/// Screen capture is handled separately via ScreenCaptureManager / RPScreenRecorder.
///
/// Three-stream architecture:
/// - Audio: captured via AVCaptureAudioDataOutput, saved to a temp WAV file
/// - Video: captured via AVCaptureVideoDataOutput, frames extracted at configurable FPS
/// - Screen: handled by ScreenCaptureManager (not this class)
///
/// All frame data is JPEG at 0.85 quality. Audio is 16-bit PCM mono at 16 kHz.
@MainActor
final class CaptureManager: NSObject, ObservableObject {

    // MARK: - Published State

    @Published var isCapturing = false
    @Published var isPaused = false
    @Published var audioLevel: Float = 0.0
    @Published var capturedFrames: [CapturedFrame] = []
    @Published var cameraPermission: CapturePermissionStatus = .notDetermined
    @Published var microphonePermission: CapturePermissionStatus = .notDetermined
    @Published var error: String?

    // MARK: - Configuration

    /// Frames per second to extract from the video stream (from AppConfig pipeline.video_capture_fps).
    var videoCaptureFPS: Double = 1.0

    /// JPEG compression quality for captured video frames.
    private let jpegQuality: CGFloat = 0.85

    /// Audio sample rate for the output WAV file.
    private let audioSampleRate: Double = 16_000
    private let audioBitsPerSample: UInt16 = 16
    private let audioChannels: UInt16 = 1

    // MARK: - AVFoundation

    private let captureSession = AVCaptureSession()
    private let audioOutput = AVCaptureAudioDataOutput()
    private let videoOutput = AVCaptureVideoDataOutput()
    private let sessionQueue = DispatchQueue(label: "com.aurion.capture.session", qos: .userInitiated)
    private let audioProcessingQueue = DispatchQueue(label: "com.aurion.capture.audio", qos: .userInitiated)
    private let videoProcessingQueue = DispatchQueue(label: "com.aurion.capture.video", qos: .userInitiated)

    // MARK: - Audio Recording State

    /// Raw PCM audio samples accumulated during recording.
    private var audioPCMData = Data()
    private let audioPCMLock = NSLock()

    // MARK: - Video Frame Extraction

    /// Timestamp of the last extracted frame, used to throttle to the configured FPS.
    private var lastFrameExtractionTime: TimeInterval = 0
    /// Session start time, used to compute relative timestamps for frames.
    private var sessionStartTime: TimeInterval = 0
    /// Reusable CIContext for frame conversion -- creating one per frame is expensive.
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    /// Maximum frames retained in memory. Older frames are dropped to prevent
    /// unbounded memory growth during long sessions.
    private let maxRetainedFrames = 300

    // MARK: - Interruption Handling

    private var interruptionObserver: NSObjectProtocol?
    private var interruptionEndObserver: NSObjectProtocol?

    // MARK: - Init / Deinit

    override init() {
        super.init()
        checkPermissions()
        registerInterruptionObservers()
    }

    deinit {
        if let observer = interruptionObserver {
            NotificationCenter.default.removeObserver(observer)
        }
        if let observer = interruptionEndObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    // MARK: - Permissions

    /// Checks current authorization status for camera and microphone.
    func checkPermissions() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: cameraPermission = .authorized
        case .denied, .restricted: cameraPermission = .denied
        case .notDetermined: cameraPermission = .notDetermined
        @unknown default: cameraPermission = .notDetermined
        }

        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: microphonePermission = .authorized
        case .denied, .restricted: microphonePermission = .denied
        case .notDetermined: microphonePermission = .notDetermined
        @unknown default: microphonePermission = .notDetermined
        }
    }

    /// Requests camera and microphone permissions. Updates published state on completion.
    func requestPermissions() async {
        let videoGranted = await AVCaptureDevice.requestAccess(for: .video)
        let audioGranted = await AVCaptureDevice.requestAccess(for: .audio)

        cameraPermission = videoGranted ? .authorized : .denied
        microphonePermission = audioGranted ? .authorized : .denied
    }

    var permissionsGranted: Bool {
        cameraPermission == .authorized && microphonePermission == .authorized
    }

    // MARK: - Session Setup

    /// Configures the AVCaptureSession with audio and video inputs/outputs.
    /// Call this once after permissions are granted, before starting capture.
    func configureCaptureSession(preferBackCamera: Bool = false) {
        sessionQueue.async { [weak self] in
            guard let self else { return }

            self.captureSession.beginConfiguration()
            self.captureSession.sessionPreset = .medium

            // --- Audio Input ---
            if let audioDevice = AVCaptureDevice.default(for: .audio),
               let audioInput = try? AVCaptureDeviceInput(device: audioDevice) {
                if self.captureSession.canAddInput(audioInput) {
                    self.captureSession.addInput(audioInput)
                }
            } else {
                Task { @MainActor in
                    self.error = "No audio device available."
                }
            }

            // --- Video Input ---
            let preferredPosition: AVCaptureDevice.Position = preferBackCamera ? .back : .front
            let videoDevice = AVCaptureDevice.default(
                .builtInWideAngleCamera,
                for: .video,
                position: preferredPosition
            ) ?? AVCaptureDevice.default(for: .video)

            if let device = videoDevice,
               let videoInput = try? AVCaptureDeviceInput(device: device) {
                if self.captureSession.canAddInput(videoInput) {
                    self.captureSession.addInput(videoInput)
                }
            } else {
                Task { @MainActor in
                    self.error = "No video device available."
                }
            }

            // --- Audio Output ---
            self.audioOutput.setSampleBufferDelegate(self, queue: self.audioProcessingQueue)
            if self.captureSession.canAddOutput(self.audioOutput) {
                self.captureSession.addOutput(self.audioOutput)
            }

            // --- Video Output ---
            self.videoOutput.setSampleBufferDelegate(self, queue: self.videoProcessingQueue)
            self.videoOutput.alwaysDiscardsLateVideoFrames = true
            self.videoOutput.videoSettings = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
            ]
            if self.captureSession.canAddOutput(self.videoOutput) {
                self.captureSession.addOutput(self.videoOutput)
            }

            self.captureSession.commitConfiguration()
        }
    }

    // MARK: - Capture Control

    /// Starts audio + video capture. The session must be configured first.
    func startCapture() {
        guard permissionsGranted else {
            error = "Camera and microphone permissions are required."
            return
        }

        // Reset state
        audioPCMLock.lock()
        audioPCMData = Data()
        audioPCMLock.unlock()

        capturedFrames = []
        lastFrameExtractionTime = 0
        sessionStartTime = Date.timeIntervalSinceReferenceDate
        error = nil

        sessionQueue.async { [weak self] in
            guard let self else { return }
            if !self.captureSession.isRunning {
                self.captureSession.startRunning()
            }
            Task { @MainActor in
                self.isCapturing = true
                self.isPaused = false
            }
        }
    }

    /// Stops capture and finalizes the audio recording.
    func stopCapture() {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            if self.captureSession.isRunning {
                self.captureSession.stopRunning()
            }
            Task { @MainActor in
                self.isCapturing = false
                self.isPaused = false
                self.audioLevel = 0.0
            }
        }
    }

    /// Pauses capture — session keeps running but samples are ignored.
    func pauseCapture() {
        guard isCapturing, !isPaused else { return }
        isPaused = true
    }

    /// Resumes capture after a pause.
    func resumeCapture() {
        guard isCapturing, isPaused else { return }
        isPaused = false
    }

    // MARK: - Audio Data Retrieval

    /// Returns the recorded audio as a WAV file Data blob.
    /// Call after `stopCapture()`. Returns nil if no audio was recorded.
    func getRecordedAudioData() -> Data? {
        audioPCMLock.lock()
        let pcmData = audioPCMData
        audioPCMLock.unlock()

        guard !pcmData.isEmpty else { return nil }
        return WAVBuilder.build(
            from: pcmData,
            sampleRate: UInt32(audioSampleRate),
            channels: audioChannels,
            bitsPerSample: audioBitsPerSample
        )
    }

    // MARK: - Interruption Handling

    private func registerInterruptionObservers() {
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVCaptureSession.wasInterruptedNotification,
            object: captureSession,
            queue: .main
        ) { [weak self] notification in
            guard let self else { return }
            let reasonValue = (notification.userInfo?[AVCaptureSession.InterruptionReasonKey] as? NSNumber)?.intValue
            let reason = AVCaptureSession.InterruptionReason(rawValue: reasonValue ?? 0)

            Task { @MainActor in
                switch reason {
                case .videoDeviceNotAvailableDueToSystemPressure:
                    self.error = "Capture paused due to system pressure."
                case .videoDeviceInUseByAnotherClient:
                    self.error = "Camera in use by another app."
                case .audioDeviceInUseByAnotherClient:
                    self.error = "Microphone in use by another app."
                default:
                    self.error = "Capture interrupted."
                }
            }
        }

        interruptionEndObserver = NotificationCenter.default.addObserver(
            forName: AVCaptureSession.interruptionEndedNotification,
            object: captureSession,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.error = nil
            }
        }
    }
}

// MARK: - AVCaptureDataOutputSampleBufferDelegate (Audio + Video)

extension CaptureManager: AVCaptureVideoDataOutputSampleBufferDelegate, AVCaptureAudioDataOutputSampleBufferDelegate {

    /// Single delegate entry point for both audio and video sample buffers.
    /// Routes to the appropriate handler based on which output produced the buffer.
    nonisolated func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        if output === audioOutput {
            handleAudioSampleBuffer(sampleBuffer)
        } else if output === videoOutput {
            handleVideoSampleBuffer(sampleBuffer)
        }
    }

    // MARK: Audio Processing

    /// Processes an audio sample buffer: computes audio level and accumulates PCM data.
    private nonisolated func handleAudioSampleBuffer(_ sampleBuffer: CMSampleBuffer) {
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        let length = CMBlockBufferGetDataLength(blockBuffer)
        guard length > 0 else { return }

        // Copy raw PCM bytes from the sample buffer
        var rawData = Data(count: length)
        rawData.withUnsafeMutableBytes { ptr in
            if let baseAddress = ptr.baseAddress {
                CMBlockBufferCopyDataBytes(blockBuffer, atOffset: 0, dataLength: length, destination: baseAddress)
            }
        }

        // --- Compute RMS audio level for the meter (0.0...1.0) ---
        let level = rawData.withUnsafeBytes { rawBuffer -> Float in
            guard let baseAddress = rawBuffer.baseAddress else { return 0 }
            let samples = baseAddress.bindMemory(to: Int16.self, capacity: length / 2)
            let sampleCount = length / 2
            guard sampleCount > 0 else { return 0 }

            var sumOfSquares: Float = 0
            for i in 0..<sampleCount {
                let sample = Float(samples[i]) / Float(Int16.max)
                sumOfSquares += sample * sample
            }
            let rms = sqrt(sumOfSquares / Float(sampleCount))
            return min(max(rms, 0), 1)
        }

        Task { @MainActor [weak self] in
            guard let self, self.isCapturing, !self.isPaused else { return }
            self.audioLevel = level
        }

        // --- Accumulate PCM data for the WAV file ---
        audioPCMLock.lock()
        audioPCMData.append(rawData)
        audioPCMLock.unlock()
    }

    // MARK: Video Processing

    /// Processes a video sample buffer: extracts a frame at the configured FPS interval.
    private nonisolated func handleVideoSampleBuffer(_ sampleBuffer: CMSampleBuffer) {
        let now = Date.timeIntervalSinceReferenceDate
        let interval = 1.0 / videoCaptureFPS

        // Throttle frame extraction to configured FPS
        guard now - lastFrameExtractionTime >= interval else { return }
        lastFrameExtractionTime = now

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        // Use the shared CIContext instead of allocating a new one per frame.
        guard let cgImage = ciContext.createCGImage(ciImage, from: ciImage.extent) else { return }

        let uiImage = UIImage(cgImage: cgImage)
        guard let jpegData = uiImage.jpegData(compressionQuality: 0.85) else { return }

        let relativeTimestamp = now - sessionStartTime
        let frame = CapturedFrame(timestamp: relativeTimestamp, imageData: jpegData)

        Task { @MainActor [weak self] in
            guard let self, self.isCapturing, !self.isPaused else { return }
            self.capturedFrames.append(frame)
            // Cap retained frames to prevent unbounded memory growth in long sessions.
            if self.capturedFrames.count > self.maxRetainedFrames {
                self.capturedFrames.removeFirst(self.capturedFrames.count - self.maxRetainedFrames)
            }
        }
    }
}

