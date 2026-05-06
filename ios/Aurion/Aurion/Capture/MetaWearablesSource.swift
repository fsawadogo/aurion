import Foundation
import Combine

/// Capture source for Meta Wearables Device Access Toolkit (Ray-Ban Meta etc.).
///
/// Surfacing logic, layered:
///   1. The user has paired a wearable over BLE (`BLEPairingManager.shared.isPaired`)
///      AND the backend feature flag `meta_wearables_enabled` is on →
///      `.ready`, ready to be selected as the active video source.
///   2. Paired but flag off → `.unavailable("Meta SDK access pending")` with a
///      detail line that still shows the device name so the clinician knows
///      pairing succeeded; the toolkit will light up when the flag flips.
///   3. Flag on but not yet paired → `.disconnected` with a "Pair via Setup"
///      hint pointing at the onboarding screen.
///   4. Default → `.unavailable("Coming soon")` (partner approval pending).
///
/// Actual SDK calls (subscribeAudio / subscribeVideo) are still stubbed — they
/// land when the iOS bundle is signed by a Meta-approved partner team and the
/// Wearables Toolkit framework is linked in. Until then `start()` throws
/// `notImplemented`.
@MainActor
final class MetaWearablesSource: CaptureSource {
    override var id: String { "meta-wearables" }
    override var displayName: String {
        if let name = BLEPairingManager.shared.pairedDeviceName {
            return name
        }
        return "Ray-Ban Meta"
    }
    override var iconSystemName: String { "eyeglasses" }
    // Video-only per the Wearables Toolkit iOS SDK — the toolkit's Camera
    // module exposes videoFramePublisher + photoDataPublisher but no mic API.
    // Audio from the glasses still goes through BT Classic → BluetoothAudioSource.
    override var capabilities: CaptureCapability { [.video] }

    private var flagCancellable: AnyCancellable?
    private var pairedCancellable: AnyCancellable?
    private var nameCancellable: AnyCancellable?

    override init() {
        super.init()
        observeFeatureFlag()
        observeBLEState()
        applyCurrentAvailability()
    }

    override func discoverIfNeeded() {
        applyCurrentAvailability()
    }

    override func start() throws {
        guard RemoteConfig.shared.featureFlags.metaWearablesEnabled else {
            throw CaptureSourceError.featureGated("Meta Wearables")
        }
        guard BLEPairingManager.shared.isPaired else {
            throw CaptureSourceError.notImplemented
        }
        // Real implementation, once partner-approved:
        //   try MetaWearables.shared.connect()
        //   try MetaWearables.shared.subscribeVideo(fps: 1) { [weak self] frame in ... }
        // The BLE pairing is the prerequisite; SDK access is the gate.
        throw CaptureSourceError.notImplemented
    }

    override func stop() {
        applyCurrentAvailability()
    }

    override func getRecordedAudioData() -> Data? { nil }

    private func observeFeatureFlag() {
        flagCancellable = RemoteConfig.shared.$featureFlags
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.applyCurrentAvailability()
            }
    }

    private func observeBLEState() {
        // Re-evaluate availability whenever pairing state or device name flips.
        pairedCancellable = BLEPairingManager.shared.$isPaired
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.applyCurrentAvailability()
            }
        nameCancellable = BLEPairingManager.shared.$pairedDeviceName
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.applyCurrentAvailability()
            }
    }

    private func applyCurrentAvailability() {
        let flagOn = RemoteConfig.shared.featureFlags.metaWearablesEnabled
        let paired = BLEPairingManager.shared.isPaired
        let name = BLEPairingManager.shared.pairedDeviceName

        switch (flagOn, paired) {
        case (true, true):
            status = .ready
            detail = "Connected · \(name ?? "Wearable") · 1080p · 60 fps"
        case (false, true):
            status = .unavailable("Meta SDK access pending")
            detail = "Paired \(name.map { "· \($0)" } ?? "") — toolkit unlocks when flag flips"
        case (true, false):
            status = .disconnected
            detail = "Pair via Setup → Devices"
        case (false, false):
            status = .unavailable("Coming soon")
            detail = "Coming soon — partner approval pending"
        }
    }
}
