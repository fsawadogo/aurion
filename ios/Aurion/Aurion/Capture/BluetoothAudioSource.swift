import Foundation
import AVFoundation
import Combine

/// Capture source for any Bluetooth audio device paired via iOS Settings —
/// AirPods, Ray-Ban Meta (audio only), lavalier mics, etc. Records via
/// AurionAudioFileRecorder so it doesn't compete with AVCaptureSession when
/// the built-in source isn't active.
///
/// Discovers itself by observing AVAudioSession route changes: whenever a
/// Bluetooth input becomes the active route, this source flips to .ready
/// and exposes the device name.
@MainActor
final class BluetoothAudioSource: CaptureSource {
    override var id: String { "bluetooth-audio" }
    override var displayName: String { connectedRouteName ?? "Bluetooth Audio" }
    override var iconSystemName: String { "headphones" }
    override var capabilities: CaptureCapability { [.audio] }

    private var connectedRouteName: String?
    private let recorder = AurionAudioFileRecorder()
    private var routeObserver: NSObjectProtocol?
    private var recordedData: Data?
    private var levelCancellable: AnyCancellable?

    override init() {
        super.init()
        observeRouteChanges()
        // Initial route read happens via discoverIfNeeded(), which the registry
        // calls after instantiating every source.

        // Mirror the helper's audio-meter into our @Published audioLevel so the
        // SourceRow waveform updates without observers having to reach inside.
        levelCancellable = recorder.$audioLevel
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.audioLevel = $0 }
    }

    override func discoverIfNeeded() {
        refreshFromCurrentRoute()
    }

    override func start() throws {
        guard let routeName = connectedRouteName else {
            throw CaptureSourceError.hardwareUnavailable("Bluetooth audio device")
        }
        status = .starting
        do {
            _ = try recorder.start(filenamePrefix: "session-bt", sessionOptions: .bluetoothInput)
        } catch {
            status = .error(error.localizedDescription)
            throw error
        }
        status = .recording
        detail = "Recording from \(routeName)"
    }

    override func pause() {
        recorder.pause()
        status = .paused
    }

    override func resume() {
        recorder.resume()
        status = .recording
    }

    override func stop() {
        if let url = recorder.stop() {
            recordedData = try? Data(contentsOf: url)
            try? FileManager.default.removeItem(at: url)
        }
        status = connectedRouteName != nil ? .ready : .disconnected
        detail = connectedRouteName.map { "Connected · \($0)" } ?? "Disconnected"
    }

    override func getRecordedAudioData() -> Data? { recordedData }

    // MARK: - Route observation

    private func observeRouteChanges() {
        routeObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.refreshFromCurrentRoute()
            }
        }
    }

    private func refreshFromCurrentRoute() {
        let route = AVAudioSession.sharedInstance().currentRoute
        let newName = route.inputs.first { Self.isBluetoothPort($0.portType) }?.portName

        // iOS fires routeChangeNotification on volume/in-ear/mute changes too.
        // Skip the @Published writes when the BT input identity hasn't moved.
        guard newName != connectedRouteName else { return }
        connectedRouteName = newName

        guard status != .recording && status != .paused else { return }
        if let newName {
            status = .ready
            detail = "Connected · \(newName)"
        } else {
            status = .disconnected
            detail = "Pair a Bluetooth device in iOS Settings"
        }
    }

    private static func isBluetoothPort(_ type: AVAudioSession.Port) -> Bool {
        type == .bluetoothHFP
            || type == .bluetoothA2DP
            || type == .bluetoothLE
    }
}
