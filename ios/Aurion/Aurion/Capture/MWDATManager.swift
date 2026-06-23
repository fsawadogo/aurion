import Combine
import CoreMedia
import Foundation
import MWDATCamera
import MWDATCore

/// Owns the Meta Wearables Device Access Toolkit (MWDAT) runtime lifecycle:
/// device registration (the real "connect to the glasses" flow that opens the
/// Meta AI app for authorization), camera permission, and the video stream
/// session. `MetaWearablesSource` reads connection state from here and drives
/// `start()`/`stop()` through `startVideoStream`/`stopVideoStream`.
///
/// This is the SDK seam, distinct from `BLEPairingManager` (a legacy
/// CoreBluetooth picker). MWDAT does NOT use custom BLE — a device is reachable
/// once it is *registered* (`Wearables.shared.devices` is non-empty). The
/// runtime is configured at launch in `AurionAppDelegate` (`Wearables.configure()`);
/// it stays inert until the `MWDAT_*` Info.plist credentials are populated.
///
/// Phase 3 (#443). Hardware-validated on a real Ray-Ban Meta — the
/// registration/permission lifecycle timing only shakes out on device.
@MainActor
final class MWDATManager: ObservableObject {
    static let shared = MWDATManager()

    /// Mirrors `MWDATCore.RegistrationState`. `.registered` means at least one
    /// pair of glasses is authorized and reachable for a session.
    enum Connection: Equatable {
        case unavailable      // SDK not configured / no credentials
        case available        // ready to register, none registered yet
        case registering      // auth in flight (Meta app handoff)
        case registered       // glasses authorized + reachable
    }

    @Published private(set) var connection: Connection = .unavailable
    @Published private(set) var isStreaming = false
    @Published private(set) var lastError: String?

    private var session: DeviceSession?
    private var stream: MWDATCamera.Stream?
    private var frameToken: (any AnyListenerToken)?
    private var stateToken: (any AnyListenerToken)?
    private var registrationTask: Task<Void, Never>?
    private var registrationObserveTask: Task<Void, Never>?

    private init() {
        observeRegistration()
    }

    /// Whether a device is registered + reachable for a streaming session.
    var isConnected: Bool { connection == .registered }

    // MARK: - Registration ("Connect glasses")

    /// Kick off the MWDAT registration flow. This hands off to the Meta AI app
    /// to authorize the glasses; the return trip arrives as a Universal Link
    /// that `MWDATLinkRouter.handle` forwards to `Wearables.shared.handleUrl`.
    func connect() {
        registrationTask?.cancel()
        registrationTask = Task { [weak self] in
            do {
                try await Wearables.shared.startRegistration()
            } catch {
                await MainActor.run { self?.lastError = "Couldn't start glasses setup: \(error.localizedDescription)" }
            }
        }
    }

    private func observeRegistration() {
        // Seed from the current state, then follow the stream. Tracked in its
        // own field (not `registrationTask`, which `connect()` overwrites) so
        // the long-lived observe loop is cancellable independently.
        apply(Wearables.shared.registrationState)
        registrationObserveTask = Task { [weak self] in
            for await state in Wearables.shared.registrationStateStream() {
                await MainActor.run { self?.apply(state) }
            }
        }
    }

    private func apply(_ state: RegistrationState) {
        switch state {
        case .unavailable: connection = .unavailable
        case .available:   connection = .available
        case .registering: connection = .registering
        case .registered:  connection = .registered
        @unknown default:  connection = .unavailable
        }
    }

    // MARK: - Video stream

    /// Request camera permission, open a device session, and start the camera
    /// stream. `onFrame` is invoked off the main actor for every video frame;
    /// the frame's `sampleBuffer` is a `CMSampleBuffer` ready for the ring.
    /// Throws on permission denial or session/stream failure.
    func startVideoStream(
        onFrame: @escaping @Sendable (CMSampleBuffer) -> Void
    ) async throws {
        lastError = nil

        let status = try await Wearables.shared.requestPermission(.camera)
        guard status == .granted else {
            throw CaptureSourceError.permissionDenied("Meta glasses camera")
        }

        // AutoDeviceSelector picks the active registered device.
        let session = try Wearables.shared.createSession(
            deviceSelector: AutoDeviceSelector(wearables: Wearables.shared)
        )
        // RAW frames (uncompressed image buffers) so the on-device masking +
        // ring/clip path can read pixel data, exactly like the iPhone camera.
        let config = StreamConfiguration(videoCodec: .raw, resolution: .high, frameRate: 5)
        guard let stream = try session.addStream(config: config) else {
            throw CaptureSourceError.hardwareUnavailable("Meta glasses camera stream")
        }

        // Subscribe BEFORE starting so no frames are missed. `listen` fires on
        // an SDK queue; the ring append is thread-safe (nonisolated).
        frameToken = stream.videoFramePublisher.listen { frame in
            onFrame(frame.sampleBuffer)
        }

        try session.start()
        await stream.start()

        self.session = session
        self.stream = stream
        isStreaming = true
    }

    /// Stop the stream + tear down the session. Idempotent.
    func stopVideoStream() async {
        await frameToken?.cancel()
        frameToken = nil
        await stateToken?.cancel()
        stateToken = nil
        if let stream { await stream.stop() }
        stream = nil
        session?.stop()
        session = nil
        isStreaming = false
    }
}
