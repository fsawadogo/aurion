import AVFoundation
import Combine
import UIKit

// MARK: - Captured Frame Model

/// Privacy-masking state of a captured frame, surfaced as a badge in
/// `FrameGalleryView` so the physician can verify the masking contract at a
/// glance (the view's stated purpose).
///
/// Live gallery frames are buffered RAW pre-upload — masking runs after
/// record-stop via `MaskingPipeline`, there is no real-time masking — so a
/// live thumbnail honestly reads `.pending`. We deliberately never label an
/// unmasked frame "Masked"; the badge always reflects the true state.
enum FrameMaskingStatus {
    /// Not yet run through `MaskingPipeline`. Faces will be masked on-device
    /// before the frame crosses any network/persistence boundary.
    case pending
    /// Confirmed masked by `MaskingPipeline` (faces blurred / PHI redacted).
    case masked
}

/// A single captured video frame with timestamp and JPEG data.
struct CapturedFrame: Identifiable {
    let id = UUID()
    let timestamp: TimeInterval
    let imageData: Data
    /// Masking state for the privacy badge in `FrameGalleryView`. Defaults to
    /// `.pending`: live frames are raw until the post-stop masking pass.
    var maskingStatus: FrameMaskingStatus = .pending
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
    nonisolated(unsafe) var videoCaptureFPS: Double = 1.0

    /// JPEG compression quality for captured video frames.
    private let jpegQuality: CGFloat = 0.85

    /// Output WAV format. Must match `AudioBufferConverter`'s output format —
    /// the converter produces 16 kHz / 16-bit / mono interleaved PCM and the
    /// WAV header is written with these same values.
    private let audioSampleRate: Double = 16_000
    private let audioBitsPerSample: UInt16 = 16
    private let audioChannels: UInt16 = 1

    /// Converts AVCaptureAudioDataOutput's native format (typically Float32 at
    /// 44.1 or 48 kHz on iOS) to 16-bit Int16 / 16 kHz / mono. Without this
    /// the WAV header would lie about the payload — see AudioBufferConverter
    /// for the full explanation.
    private let audioConverter = AudioBufferConverter()

    /// Optional parallel consumer of the raw audio sample buffers. Set by
    /// SessionManager when a `LiveTranscriber` is wired up; called on the
    /// audio delegate queue *in addition to* the existing converter +
    /// PCM-accumulation path. Non-disruptive: the WAV upload pipeline and
    /// audio-level meter are unchanged regardless of whether this is set.
    nonisolated(unsafe) var sampleBufferTap: (@Sendable (CMSampleBuffer) -> Void)?

    // MARK: - AVFoundation

    private nonisolated(unsafe) let captureSession = AVCaptureSession()

    /// The underlying AVCaptureSession, surfaced so a SwiftUI view can attach
    /// an AVCaptureVideoPreviewLayer for live preview. Read-only from outside
    /// — callers must not mutate inputs/outputs directly.
    nonisolated var previewSession: AVCaptureSession { captureSession }
    private nonisolated(unsafe) let audioOutput = AVCaptureAudioDataOutput()
    private nonisolated(unsafe) let videoOutput = AVCaptureVideoDataOutput()
    private let sessionQueue = DispatchQueue(label: "com.aurion.capture.session", qos: .userInitiated)
    private let audioProcessingQueue = DispatchQueue(label: "com.aurion.capture.audio", qos: .userInitiated)
    private let videoProcessingQueue = DispatchQueue(label: "com.aurion.capture.video", qos: .userInitiated)

    // MARK: - Audio Recording State

    /// Raw PCM audio accumulated during recording. Thread-safe and gated on
    /// the capture-active state so paused / pre-start / post-stop buffers
    /// never reach the WAV (#281) — written from the nonisolated audio
    /// delegate queue, controlled from the main actor.
    private let audioBuffer = AudioCaptureBuffer()

    // MARK: - Video Frame Extraction

    /// Timestamp of the last extracted frame, used to throttle to the configured FPS.
    private nonisolated(unsafe) var lastFrameExtractionTime: TimeInterval = 0
    /// Session start time, used to compute relative timestamps for frames.
    private nonisolated(unsafe) var sessionStartTime: TimeInterval = 0
    /// Reusable CIContext for frame conversion -- creating one per frame is expensive.
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])

    /// Maximum frames retained in memory. Older frames are dropped to prevent
    /// unbounded memory growth during long sessions.
    private let maxRetainedFrames = 300

    // MARK: - Video Ring Buffer (P1-4 dual-mode foundation)

    /// Default cap until AppConfig wiring lands in P1-5:
    /// `clip_ring_buffer_seconds (15) × videoCaptureFPS (1) = 15 entries`.
    /// The plan calls for these to come from `RemoteConfig.pipeline` once
    /// the backend `ClientPipelineResponse` is extended (P1-1). Until
    /// then, defaults match the dual-mode plan's documented values so the
    /// memory footprint is the same as the eventual prod path.
    private static let defaultClipRingBufferSeconds: Double = 15

    /// Rolling window of raw sample buffers, drained on demand by the
    /// P1-5 dispatcher to produce a `.mp4` for masking + upload. Runs
    /// in parallel with the existing per-frame JPEG extractor; the frame
    /// path is unchanged. NEVER uploaded raw — see `VideoRingBuffer`'s
    /// privacy contract.
    let clipRingBuffer: VideoRingBuffer

    // MARK: - Interruption Handling

    private var interruptionObserver: NSObjectProtocol?
    private var interruptionEndObserver: NSObjectProtocol?

    // MARK: - Init / Deinit

    override init() {
        // Compute the ring's item cap from the default video FPS — when
        // RemoteConfig lands the value in `videoCaptureFPS`, P1-5 will
        // rebuild the ring with the live cap. For P1-4 we lock to the
        // documented defaults; the ring is only filled, never extracted.
        let maxItems = max(1, Int(Self.defaultClipRingBufferSeconds * 1.0))
        self.clipRingBuffer = VideoRingBuffer(maxItems: maxItems, captureFPS: 1.0)
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

    /// Tracks which camera position the session is currently configured for.
    /// Used to skip reconfiguration when nothing has changed — important
    /// because the preview layer (CameraPreviewLayer) may already be
    /// rendering from this session, and destructively removing + re-adding
    /// inputs while the render thread is mid-frame causes EXC_BAD_ACCESS.
    private nonisolated(unsafe) var configuredCameraPosition: AVCaptureDevice.Position?

    /// Tracks whether the active capture session has the video input/output
    /// wired up. Audio-only modes set this to false so the camera stays
    /// dark and the LED never lights — a real privacy signal to the
    /// patient and clinician.
    private nonisolated(unsafe) var configuredCaptureVideo: Bool = true

    /// Configures the AVCaptureSession with audio and video inputs/outputs.
    /// Idempotent in the common case — if the session already has the
    /// requested camera position wired up, this is a no-op. The destructive
    /// remove-and-rewire path only runs when the camera position actually
    /// changes (e.g., flip from back to front camera).
    ///
    /// Defaults to the back camera — clinical use case is the physician's
    /// phone pointing at the patient. Front-camera capture is opt-in.
    func configureCaptureSession(preferBackCamera: Bool = true, captureVideo: Bool = true) {
        let requestedPosition: AVCaptureDevice.Position = preferBackCamera ? .back : .front
        sessionQueue.async { [weak self] in
            guard let self else { return }

            // Fast path: if the session is already wired for this camera and
            // matches the current video toggle, there's nothing to do.
            // Returning here avoids the destructive remove+re-add that
            // races with the preview layer's render thread when start() is
            // called on a running session.
            if self.configuredCameraPosition == requestedPosition,
               self.configuredCaptureVideo == captureVideo,
               !self.captureSession.inputs.isEmpty,
               !self.captureSession.outputs.isEmpty {
                return
            }

            self.captureSession.beginConfiguration()
            self.captureSession.sessionPreset = .medium

            for input in self.captureSession.inputs {
                self.captureSession.removeInput(input)
            }
            for output in self.captureSession.outputs {
                self.captureSession.removeOutput(output)
            }

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

            // --- Video Input + Output (skipped when audio-only) ---
            if captureVideo {
                let videoDevice = AVCaptureDevice.default(
                    .builtInWideAngleCamera,
                    for: .video,
                    position: requestedPosition
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
            }

            // --- Audio Output ---
            self.audioOutput.setSampleBufferDelegate(self, queue: self.audioProcessingQueue)
            if self.captureSession.canAddOutput(self.audioOutput) {
                self.captureSession.addOutput(self.audioOutput)
            }

            // --- Video Output ---
            if captureVideo {
                self.videoOutput.setSampleBufferDelegate(self, queue: self.videoProcessingQueue)
                self.videoOutput.alwaysDiscardsLateVideoFrames = true
                self.videoOutput.videoSettings = [
                    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
                ]
                if self.captureSession.canAddOutput(self.videoOutput) {
                    self.captureSession.addOutput(self.videoOutput)
                }
            }

            self.captureSession.commitConfiguration()
            self.configuredCameraPosition = requestedPosition
            self.configuredCaptureVideo = captureVideo
        }
    }

    // MARK: - Capture Control

    /// Starts audio + video capture. The session must be configured first.
    func startCapture() {
        guard permissionsGranted else {
            error = "Camera and microphone permissions are required."
            return
        }

        // Reset state — clears the buffer and leaves it inactive until
        // capture actually starts below (so no pre-start buffers leak).
        audioBuffer.reset()
        // Drop the converter's lazy state so it picks up the current input
        // format (handles mic route changes between sessions, e.g. AirPods
        // unplugged before recording starts).
        audioConverter.reset()

        capturedFrames = []
        // Drop any sample buffers held over from a previous session so the
        // pixel-buffer pool can reclaim them. Without this, the ring would
        // carry stale frames into the new session — fine functionally
        // (they'd age out within the cap), but wasteful of memory.
        clipRingBuffer.clear()
        lastFrameExtractionTime = 0
        sessionStartTime = Date.timeIntervalSinceReferenceDate
        error = nil

        sessionQueue.async { [weak self] in
            guard let self else { return }
            // Activate the shared AVAudioSession ON the same serial queue as
            // startRunning, BEFORE startRunning fires. Without this the
            // capture source bails with FigCaptureSourceRemote err=-17281
            // and FigAudioSession err=-19224 (Apple's internal "audio session
            // not in record state" check).
            //
            // First setActive(false) to reset any stale state from a previous
            // crashed session or from voice enrollment — without the reset,
            // a sticky inactive-but-not-fully-torn-down session can refuse to
            // re-activate. Then setCategory(.record) — no playback in this
            // path so .playAndRecord adds routing complexity for no gain.
            // No .mixWithOthers / .defaultToSpeaker either — AVCaptureSession
            // wants primary mic ownership.
            do {
                let session = AVAudioSession.sharedInstance()
                try? session.setActive(false, options: .notifyOthersOnDeactivation)
                try session.setCategory(
                    .record,
                    mode: .default,
                    options: [.allowBluetoothHFP]
                )
                try session.setActive(true, options: .notifyOthersOnDeactivation)
                NSLog("[Aurion] AVAudioSession ready: cat=%@ mode=%@ sampleRate=%.0f",
                      session.category.rawValue,
                      session.mode.rawValue,
                      session.sampleRate)
            } catch {
                NSLog("[Aurion] AVAudioSession activate FAILED: %@",
                      error.localizedDescription)
                Task { @MainActor in
                    self.error = "Audio session activation failed: \(error.localizedDescription)"
                }
                return
            }

            if !self.captureSession.isRunning {
                self.captureSession.startRunning()
                NSLog("[Aurion] AVCaptureSession started: inputs=%d outputs=%d",
                      self.captureSession.inputs.count,
                      self.captureSession.outputs.count)
            }
            // Open the audio gate now that the session is running so the
            // recorded PCM tracks the live capture window.
            self.audioBuffer.activate()
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
            // Close the audio gate — no more samples accepted. The buffered
            // PCM is retained for getRecordedAudioData() to build the WAV.
            self.audioBuffer.deactivate()
            // Release the audio session so other apps (Music, FaceTime, etc.)
            // regain priority. `notifyOthersOnDeactivation` lets paused apps
            // automatically resume playback. Non-fatal if it fails.
            try? AVAudioSession.sharedInstance().setActive(
                false,
                options: .notifyOthersOnDeactivation
            )
            // Release the retained sample buffers on stop. The dispatcher
            // (P1-5) extracts on trigger, mid-session — at session stop
            // there's no consumer left and the ring would otherwise hold
            // ~15 frames until the next start. Clearing here also keeps the
            // privacy surface narrow: raw frames don't outlive the active
            // capture session.
            self.clipRingBuffer.clear()
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
        // Close the audio gate so paused audio is genuinely not recorded
        // (#281) — pause is a consent boundary, not just a UI state.
        audioBuffer.deactivate()
    }

    /// Resumes capture after a pause.
    func resumeCapture() {
        guard isCapturing, isPaused else { return }
        isPaused = false
        audioBuffer.activate()
    }

    // MARK: - Audio Data Retrieval

    /// Returns the recorded audio as a WAV file Data blob.
    /// Call after `stopCapture()`. Returns nil if no audio was recorded.
    func getRecordedAudioData() -> Data? {
        let pcmData = audioBuffer.snapshot()

        guard !pcmData.isEmpty else { return nil }
        return WAVBuilder.build(
            from: pcmData,
            sampleRate: UInt32(audioSampleRate),
            channels: audioChannels,
            bitsPerSample: audioBitsPerSample
        )
    }

    /// Drop the in-memory audio PCM. Called by `LocalDataPurger` after
    /// export — the WAV bytes never need to outlive the upload + export.
    func discardRecordedAudio() {
        audioBuffer.reset()
    }

    /// Cheap byte-count for the audit log — no WAV construction, no
    /// PCM copy. The lock protects against concurrent writes from the
    /// audio delegate queue.
    func getRecordedAudioByteCount() -> Int {
        audioBuffer.byteCount
    }

    /// Recorded audio as an `AVAudioPCMBuffer` of floats so downstream
    /// consumers can slice by timestamps without re-parsing WAV bytes.
    func getRecordedPCMBuffer() -> AVAudioPCMBuffer? {
        let pcmData = audioBuffer.snapshot()

        guard !pcmData.isEmpty,
              let format = AVAudioFormat(
                  commonFormat: .pcmFormatFloat32,
                  sampleRate: audioSampleRate,
                  channels: AVAudioChannelCount(audioChannels),
                  interleaved: false
              ) else {
            return nil
        }

        let bytesPerSample = Int(audioBitsPerSample) / 8
        let frameCount = pcmData.count / bytesPerSample / Int(audioChannels)
        guard frameCount > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frameCount)) else {
            return nil
        }
        buffer.frameLength = AVAudioFrameCount(frameCount)

        // Convert int16-LE PCM bytes into normalized float samples on the
        // single channel. We capture at 16 kHz mono int16 (see audioSampleRate
        // and audioBitsPerSample above); if those constants change this
        // conversion must be revisited.
        guard let channelPtr = buffer.floatChannelData?[0] else { return nil }
        pcmData.withUnsafeBytes { rawBuffer in
            guard let int16Ptr = rawBuffer.bindMemory(to: Int16.self).baseAddress else { return }
            let scale: Float = 1.0 / Float(Int16.max)
            for i in 0..<frameCount {
                channelPtr[i] = Float(int16Ptr[i]) * scale
            }
        }
        return buffer
    }

    // MARK: - Interruption Handling

    private func registerInterruptionObservers() {
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVCaptureSession.wasInterruptedNotification,
            object: captureSession,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.error = "Capture interrupted."
            }
        }

        interruptionEndObserver = NotificationCenter.default.addObserver(
            forName: AVCaptureSession.interruptionEndedNotification,
            object: captureSession,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
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

    /// Processes an audio sample buffer: converts the native capture format
    /// (typically Float32 @ 44.1/48 kHz on iOS) to 16-bit Int16 / 16 kHz /
    /// mono, computes the meter level on the converted buffer, and appends
    /// the PCM bytes to the recording. The conversion is what makes the WAV
    /// header truthful — without it Whisper transcribes garbled audio.
    private nonisolated func handleAudioSampleBuffer(_ sampleBuffer: CMSampleBuffer) {
        guard let result = audioConverter.convert(sampleBuffer) else { return }

        // Fan-out the raw sample buffer to any parallel consumer (currently
        // only LiveTranscriber). Done before the published-state hop so
        // captioning starts as early as possible. Tap closure is itself
        // responsible for thread-hopping if needed.
        sampleBufferTap?(sampleBuffer)

        Task { @MainActor [weak self] in
            guard let self, self.isCapturing, !self.isPaused else { return }
            self.audioLevel = result.rms
        }

        // Gated append — a no-op while paused / before start / after stop,
        // so non-consented audio never reaches the WAV (#281).
        audioBuffer.append(result.pcm)
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

        // AVFoundation recycles pixel buffers aggressively when alwaysDiscardsLateVideoFrames
        // is on. Lock the base address while we read so the bytes can't be reclaimed mid-encode.
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let sourceImage = CIImage(cvPixelBuffer: pixelBuffer)

        // Vision providers don't need 12 MP — clamp the long edge to keep JPEG encode fast
        // enough to finish before the next sample buffer arrives.
        let maxEdge: CGFloat = 1280
        let longest = max(sourceImage.extent.width, sourceImage.extent.height)
        let scale: CGFloat = longest > maxEdge ? maxEdge / longest : 1.0
        let scaled = scale < 1.0
            ? sourceImage.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            : sourceImage

        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
        guard let jpegData = ciContext.jpegRepresentation(
            of: scaled,
            colorSpace: colorSpace,
            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.85]
        ) else { return }

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

        // P1-4: ring-buffer the raw sample buffer in parallel with the JPEG
        // extractor above. The ring is an additive sink — the frame path
        // already published `frame` to `capturedFrames` and that's what the
        // existing Stage 2 pipeline still consumes. The ring is only drained
        // by P1-5's dispatcher when AppConfig opts in to clip evidence.
        //
        // Capture-side guards (isCapturing, isPaused) live on @MainActor
        // state we can't read here without hopping; in practice this delegate
        // only fires while the AVCaptureSession is running, and the ring is
        // explicitly cleared on stopCapture above, so the contract holds.
        clipRingBuffer.append(sampleBuffer, at: now)
    }
}

