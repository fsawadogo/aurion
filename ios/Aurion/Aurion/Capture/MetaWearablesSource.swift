import Combine
import CoreMedia
import Foundation

/// Capture source for Meta Wearables (Ray-Ban Meta) video, via MWDAT (#443).
///
/// Surfacing logic, layered:
///   1. `meta_wearables_enabled` flag ON + glasses registered → `.ready`.
///   2. Flag ON + not registered → `.disconnected` ("Connect in Setup → Devices").
///   3. Flag OFF + registered → `.unavailable("Meta SDK access pending")`.
///   4. Default → `.unavailable("Coming soon")`.
///
/// Streaming: `start()` drives `MWDATManager.startVideoStream`; each delivered
/// `CMSampleBuffer` is appended to `clipRingBuffer` on the SDK queue (the ring
/// is thread-safe). The cadence-clip driver in `SessionManager` then extracts
/// trailing clips exactly as it does for the iPhone camera — so the masking +
/// vision pipeline needs no change. Audio for a glasses session comes from a
/// separate source (iPhone mic or the glasses mic over Bluetooth Classic);
/// MWDAT's camera module is video-only.
@MainActor
final class MetaWearablesSource: CaptureSource, VideoClipSource {
    override var id: String { "meta-wearables" }
    override var displayName: String {
        BLEPairingManager.shared.pairedDeviceName ?? "Ray-Ban Meta"
    }
    override var iconSystemName: String { "eyeglasses" }
    override var capabilities: CaptureCapability { [.video] }

    // MARK: VideoClipSource

    /// Raw (unmasked) ring of recent frames — never uploaded; cleared on stop.
    /// Sized by `applyPipelineConfig`; self-configures on `start()` as a
    /// fallback so it works even if the cold-start path only configures the
    /// built-in camera.
    private(set) var clipRingBuffer = VideoRingBuffer(maxItems: 8, captureFPS: 5.0)

    private let mwdat = MWDATManager.shared
    private var cancellables = Set<AnyCancellable>()
    /// Wall-clock baseline (Date.timeIntervalSinceReferenceDate) set on start,
    /// matching the ring's append/extract clock — see `CaptureManager`.
    private var sessionStartTime: TimeInterval = 0

    override init() {
        super.init()
        observeAvailability()
    }

    override func discoverIfNeeded() {
        applyCurrentAvailability()
    }

    // MARK: Lifecycle

    override func start() throws {
        guard RemoteConfig.shared.featureFlags.metaWearablesEnabled else {
            throw CaptureSourceError.featureGated("Meta Wearables")
        }
        guard mwdat.isConnected else {
            throw CaptureSourceError.hardwareUnavailable("Meta glasses (not connected)")
        }
        status = .starting
        sessionStartTime = Date.timeIntervalSinceReferenceDate
        // Capture the ring locally so the off-main SDK frame callback never
        // touches @MainActor `self`. `VideoRingBuffer` is thread-safe
        // (`append` is nonisolated); the ring is final by `start()` because
        // `applyPipelineConfig` runs first.
        let ring = clipRingBuffer

        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await self.mwdat.startVideoStream { sampleBuffer in
                    ring.append(sampleBuffer, at: Date.timeIntervalSinceReferenceDate)
                }
                self.status = .recording
                self.detail = "Streaming · \(self.displayName)"
            } catch {
                self.status = .error(error.localizedDescription)
                self.detail = error.localizedDescription
            }
        }
    }

    override func stop() {
        Task { @MainActor [weak self] in
            await self?.mwdat.stopVideoStream()
            self?.clipRingBuffer.clear()
            self?.applyCurrentAvailability()
        }
    }

    override func getRecordedAudioData() -> Data? { nil }

    // MARK: VideoClipSource conformance

    func applyPipelineConfig(videoCaptureFPS fps: Double, clipWindowMs: Int) {
        let safeFPS = min(max(fps, 1.0), 8.0)
        let windowSeconds = Double(max(clipWindowMs, 1_000)) / 1_000.0
        // Span the window (+2s headroom) at the capture rate, with a small floor.
        let neededForWindow = Int(((windowSeconds + 2.0) * safeFPS).rounded(.up))
        let maxItems = max(8, neededForWindow)
        clipRingBuffer = VideoRingBuffer(maxItems: maxItems, captureFPS: safeFPS)
    }

    func extractCadenceClip(windowMs: Int) async -> (url: URL, timestampMs: Int)? {
        guard windowMs > 0 else { return nil }
        let now = Date.timeIntervalSinceReferenceDate
        // Reuse the exact window math the built-in camera path uses so the
        // session-relative timestamp + center are computed identically.
        let w = CaptureManager.cadenceClipWindow(
            now: now, sessionStart: sessionStartTime, windowMs: windowMs
        )
        do {
            let url = try await clipRingBuffer.extract(around: w.center, duration: w.durationSeconds)
            return (url, w.timestampMs)
        } catch {
            NSLog("[Aurion] Meta extractCadenceClip skipped: %@", String(describing: error))
            return nil
        }
    }

    // MARK: Availability

    private func observeAvailability() {
        RemoteConfig.shared.$featureFlags
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.applyCurrentAvailability() }
            .store(in: &cancellables)
        mwdat.$connection
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.applyCurrentAvailability() }
            .store(in: &cancellables)
    }

    private func applyCurrentAvailability() {
        // Don't clobber an active recording's status.
        if status == .starting || status == .recording { return }

        let flagOn = RemoteConfig.shared.featureFlags.metaWearablesEnabled
        let registered = mwdat.isConnected
        let name = BLEPairingManager.shared.pairedDeviceName

        switch (flagOn, registered) {
        case (true, true):
            status = .ready
            detail = "Connected · \(name ?? "Ray-Ban Meta")"
        case (true, false):
            status = .disconnected
            detail = "Connect in Setup → Devices"
        case (false, true):
            status = .unavailable("Meta SDK access pending")
            detail = "Registered \(name.map { "· \($0)" } ?? "") — enable in feature flags"
        case (false, false):
            status = .unavailable("Coming soon")
            detail = "Coming soon — enable Meta Wearables to connect"
        }
    }
}
