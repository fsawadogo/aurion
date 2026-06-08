import Foundation
import Combine
import AVFoundation
import CoreMedia

/// Capture source backed by the iPhone's built-in mic + camera via AVCaptureSession.
/// Always available — this is the safe fallback when no other source is selected
/// or when an active source disconnects mid-session.
@MainActor
final class BuiltInCaptureSource: CaptureSource {
    override var id: String { "builtin" }
    override var displayName: String { "iPhone Camera + Mic" }
    override var iconSystemName: String { "iphone" }
    override var capabilities: CaptureCapability { [.audio, .video] }

    /// Mirrors of the underlying CaptureManager's permission state, surfaced
    /// here so DeviceHubView (and anyone else) can drive UI off the registry
    /// without instantiating a second CaptureManager.
    @Published private(set) var cameraPermission: CapturePermissionStatus = .notDetermined
    @Published private(set) var microphonePermission: CapturePermissionStatus = .notDetermined

    /// Active back-camera lens: `false` = standard (1×), `true` = ultra-wide
    /// (0.5×). Published so the capture controls reflect the live lens. Mirror
    /// of the underlying CaptureManager.
    @Published private(set) var useUltraWide: Bool = false

    private let manager: CaptureManager
    private var cancellables = Set<AnyCancellable>()

    override init() {
        self.manager = CaptureManager()
        super.init()
        bind()
    }

    private func bind() {
        manager.$audioLevel
            .receive(on: RunLoop.main)
            .assign(to: &$audioLevel)
        manager.$cameraPermission
            .receive(on: RunLoop.main)
            .assign(to: &$cameraPermission)
        manager.$microphonePermission
            .receive(on: RunLoop.main)
            .assign(to: &$microphonePermission)

        Publishers.CombineLatest3(manager.$cameraPermission, manager.$microphonePermission, manager.$isCapturing)
            .receive(on: RunLoop.main)
            .sink { [weak self] camera, mic, capturing in
                guard let self else { return }
                if mic == .denied || camera == .denied {
                    self.status = .unavailable("Camera or microphone permission denied.")
                } else if capturing {
                    self.status = self.manager.isPaused ? .paused : .recording
                } else {
                    self.status = .ready
                }
                // The meter UI reads audioLevel directly; keeping a dB string
                // here would go stale because this sink doesn't fire on level ticks.
                self.detail = capturing
                    ? "Recording"
                    : (self.manager.permissionsGranted ? "Ready" : "Tap to grant permissions")
            }
            .store(in: &cancellables)

        manager.$capturedFrames
            .receive(on: RunLoop.main)
            .assign(to: &$capturedFrames)

        manager.$useUltraWide
            .receive(on: RunLoop.main)
            .assign(to: &$useUltraWide)
    }

    override func discoverIfNeeded() {
        manager.checkPermissions()
        if manager.permissionsGranted {
            status = .ready
        } else if manager.cameraPermission == .denied || manager.microphonePermission == .denied {
            status = .unavailable("Camera or microphone permission denied.")
        } else {
            status = .disconnected
        }
    }

    /// Re-reads the system permission state. Cheap — wraps a synchronous
    /// AVCaptureDevice.authorizationStatus query. Call when returning from
    /// the foreground in case the user toggled permissions in iOS Settings.
    func refreshPermissions() {
        manager.checkPermissions()
    }

    /// Triggers iOS's camera + microphone permission prompts iff the system
    /// status is still `.notDetermined`. iOS only shows the prompt the first
    /// time `requestAccess` is called per app install — once the user has
    /// answered, this is a no-op. Idempotent and safe to call from the
    /// session start path.
    func ensurePermissions() async {
        manager.checkPermissions()
        let needsCamera = manager.cameraPermission == .notDetermined
        let needsMic = manager.microphonePermission == .notDetermined
        guard needsCamera || needsMic else { return }
        await manager.requestPermissions()
    }

    /// Optional parallel consumer of raw audio sample buffers. SessionManager
    /// wires this to LiveTranscriber so live captions can run alongside the
    /// canonical Whisper batch transcription. Setting nil tears down the
    /// fan-out cleanly.
    var sampleBufferTap: (@Sendable (CMSampleBuffer) -> Void)? {
        get { manager.sampleBufferTap }
        set { manager.sampleBufferTap = newValue }
    }

    /// Underlying AVCaptureSession — exposed for CameraPreviewLayer to wire
    /// an AVCaptureVideoPreviewLayer onto. Same instance the capture pipeline
    /// uses; the preview is a sibling output, not a fork.
    var previewSession: AVCaptureSession { manager.previewSession }

    /// True only after the underlying AVCaptureSession is fully running with
    /// inputs/outputs configured. SwiftUI views should gate the preview on
    /// this rather than on `status` or `session.state`, both of which can
    /// flip to "recording" before the capture pipeline is actually live.
    var isReadyForPreview: Bool {
        manager.permissionsGranted && status == .recording
    }

    /// Set by SessionManager before `start()` to gate the camera input.
    /// False keeps the LED dark in audio-only modes.
    var includeVideo: Bool = true

    /// Whether this device has a back ultra-wide (0.5×) lens. Drives the
    /// capture screen's 0.5× toggle visibility. `false` on the Simulator (no
    /// camera) so the control stays hidden there.
    var ultraWideAvailable: Bool { manager.ultraWideAvailable }

    /// Switches the back camera between standard (1×) and ultra-wide (0.5×).
    /// Falls back to wide + publishes `useUltraWide = false` when the device
    /// lacks an ultra-wide lens. Safe to call before or during a live session.
    func setUltraWide(_ enabled: Bool) {
        manager.setUltraWide(enabled)
    }

    /// Rolling video sample buffer ring, pumped by the underlying
    /// CaptureManager during active recording. Exposed so the P1-5
    /// dual-mode dispatcher can extract clip windows on trigger without
    /// reaching into the manager directly.
    ///
    /// Per the VideoRingBuffer privacy contract: this returns RAW
    /// (unmasked) sample buffers. The caller MUST run any extracted
    /// MP4 through `MaskingPipeline.maskClip` before any network or
    /// persistence boundary.
    var clipRingBuffer: VideoRingBuffer { manager.clipRingBuffer }

    override func start() throws {
        guard manager.permissionsGranted else {
            throw CaptureSourceError.permissionDenied("camera and microphone")
        }
        status = .starting
        // Back camera is the right default for the clinical scribe use case —
        // the physician points the phone at the patient / wound / exam area.
        // Front camera was the previous default but produced selfie footage,
        // which is never what we want for Stage 2 visual enrichment.
        manager.configureCaptureSession(preferBackCamera: true, captureVideo: includeVideo)
        manager.startCapture()
    }

    override func pause() { manager.pauseCapture() }
    override func resume() { manager.resumeCapture() }
    override func stop() { manager.stopCapture() }

    override func getRecordedAudioData() -> Data? {
        manager.getRecordedAudioData()
    }

    override func getRecordedPCMBuffer() -> AVAudioPCMBuffer? {
        manager.getRecordedPCMBuffer()
    }

    override func discardRecordedAudio() {
        manager.discardRecordedAudio()
    }

    override func getRecordedAudioByteCount() -> Int {
        manager.getRecordedAudioByteCount()
    }
}
