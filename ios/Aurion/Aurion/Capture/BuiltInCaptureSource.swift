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

    override func start() throws {
        guard manager.permissionsGranted else {
            throw CaptureSourceError.permissionDenied("camera and microphone")
        }
        status = .starting
        manager.configureCaptureSession(preferBackCamera: false)
        manager.startCapture()
    }

    override func pause() { manager.pauseCapture() }
    override func resume() { manager.resumeCapture() }
    override func stop() { manager.stopCapture() }

    override func getRecordedAudioData() -> Data? {
        manager.getRecordedAudioData()
    }
}
