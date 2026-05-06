@preconcurrency import CoreBluetooth
import Combine
import Foundation

// MARK: - Connection State

/// Represents the current BLE connection lifecycle state.
enum BLEConnectionState: String {
    case disconnected
    case scanning
    case connecting
    case connected
    case recovering  // Attempting to reconnect after failover
    case failedOver
}

// MARK: - Discovered Device (UI-facing)

/// Public-facing representation of a peripheral the picker can render.
/// Wrapping CBPeripheral keeps SwiftUI views from importing CoreBluetooth and
/// makes the discovered list trivially `Equatable` for diffable updates.
struct BLEDiscoveredDevice: Identifiable, Equatable, Hashable {
    let id: UUID         // peripheral.identifier
    var name: String
    var rssi: Int
}

// MARK: - BLE Pairing Manager

/// BLE pairing manager for wearable devices (Ray-Ban Meta and any
/// compatible Bluetooth glasses / capture wearable).
/// Handles scanning, pairing, connection monitoring, and auto-failover.
///
/// When the glasses disconnect unexpectedly, the manager attempts to reconnect
/// up to 3 times with exponential backoff (2s, 4s, 8s). If all attempts fail,
/// it fires the `onDeviceFailover` callback so the app can switch to the
/// iPhone/iPad camera.
///
/// On the iOS Simulator there is no Bluetooth radio, so `simulatedMode`
/// defaults to true and a small set of synthetic devices is published so the
/// pairing UX can be exercised end-to-end.
@MainActor
final class BLEPairingManager: NSObject, ObservableObject {

    static let shared = BLEPairingManager()

    // MARK: - Published State

    @Published var isPaired = false
    @Published var isScanning = false
    @Published var pairedDeviceName: String?
    @Published var pairedDeviceId: UUID?
    @Published var connectionState: BLEConnectionState = .disconnected
    @Published var bluetoothEnabled = false
    @Published var signalStrength: Int = -100
    @Published var error: String?
    /// Devices the picker should render. Updated as `didDiscover` fires.
    @Published var discoveredDevices: [BLEDiscoveredDevice] = []

    // MARK: - Callbacks

    /// Called when the glasses fail to reconnect and the system should fall back to the device camera.
    var onDeviceFailover: ((String) -> Void)?

    // MARK: - Configuration

    /// When true, simulates BLE discovery and pairing for Simulator / no-hardware testing.
    /// Defaults to true on the simulator (no Bluetooth radio exists there) so the
    /// pairing UX is testable; on device this is false unless the caller flips it.
    #if targetEnvironment(simulator)
    var simulatedMode = true
    #else
    var simulatedMode = false
    #endif

    /// Maximum number of reconnection attempts after unexpected disconnect.
    private let maxReconnectAttempts = 3

    /// Delay between reconnection attempts in seconds.
    private let reconnectDelaySeconds: TimeInterval = 2.0

    /// Timeout for scanning before giving up (seconds).
    private let scanTimeoutSeconds: TimeInterval = 30.0

    /// UserDefaults key for the last successfully paired peripheral UUID.
    /// Storing only the UUID — never advertised name or anything else — keeps
    /// the on-disk footprint to the minimum needed to retrieve the peripheral
    /// via `CBCentralManager.retrievePeripherals(withIdentifiers:)` next launch.
    private static let pairedPeripheralIdKey = "aurion.ble.pairedPeripheralId"

    // MARK: - Known Ray-Ban Meta BLE Identifiers

    /// Known BLE service UUIDs for Ray-Ban Meta Smart Glasses.
    /// These may change with firmware updates — kept configurable.
    private static let knownServiceUUIDs: [CBUUID] = [
        // Meta companion service — primary pairing UUID
        CBUUID(string: "FE2C1000-8366-4814-8EB0-01DE32100BEA"),
    ]

    /// Fallback name fragments for discovery when service UUIDs are not advertised.
    /// We accept a permissive set so users can pair non-Meta wearables (body
    /// cams, third-party glasses) as well — the audio/video integration is
    /// gated downstream by feature flags, not by the BLE filter.
    private static let nameMatchPatterns: [String] = [
        "ray-ban",
        "ray ban",
        "meta",
        "stories",       // Ray-Ban Stories (Gen 1)
        "wayfarer",      // Ray-Ban Meta Wayfarer
        "glasses",
        "wearable",
        "cam",
        "aurion",
    ]

    // MARK: - CoreBluetooth

    private var centralManager: CBCentralManager!
    private var connectedPeripheral: CBPeripheral?
    private var discoveredPeripherals: [CBPeripheral] = []

    // MARK: - Reconnection State

    private var reconnectAttempts = 0
    private var isAutoReconnecting = false
    private var scanTimer: Timer?
    private var reconnectTimer: Timer?

    /// The session ID for audit logging, set externally when a session is active.
    var activeSessionId: String?

    // MARK: - Init

    override init() {
        super.init()
        centralManager = CBCentralManager(delegate: self, queue: nil)
        // Restore is attempted on the first centralManagerDidUpdateState callback
        // once the radio reports `.poweredOn`; CoreBluetooth refuses earlier.
    }

    // MARK: - Scanning

    /// Start scanning for compatible wearables.
    func startScanning() {
        guard !simulatedMode else {
            simulateDiscovery()
            return
        }

        guard centralManager.state == .poweredOn else {
            error = "Bluetooth is not available. Please enable Bluetooth in Settings."
            return
        }

        guard !isScanning else { return }

        error = nil
        discoveredPeripherals = []
        discoveredDevices = []
        isScanning = true
        connectionState = .scanning

        // Scan broadly — we filter by name/service in didDiscover. Passing nil
        // for services is the only way to also pick up devices that don't
        // advertise our known service UUIDs.
        centralManager.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )

        // Auto-stop scanning after timeout
        scanTimer?.invalidate()
        scanTimer = Timer.scheduledTimer(withTimeInterval: scanTimeoutSeconds, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.isScanning else { return }
                self.stopScanning()
                if !self.isPaired && self.discoveredDevices.isEmpty {
                    self.error = "No devices found. Make sure your wearable is powered on and nearby."
                }
            }
        }
    }

    /// Stop scanning for peripherals.
    func stopScanning() {
        scanTimer?.invalidate()
        scanTimer = nil

        guard !simulatedMode else {
            isScanning = false
            if connectionState == .scanning { connectionState = .disconnected }
            return
        }

        if centralManager.isScanning {
            centralManager.stopScan()
        }
        isScanning = false
        if connectionState == .scanning {
            connectionState = .disconnected
        }
    }

    // MARK: - Connection

    /// Connect by the public-facing device id (peripheral UUID).
    /// Used by the pairing picker so views never have to touch CBPeripheral.
    func connect(deviceId: UUID) {
        guard !simulatedMode else {
            let name = discoveredDevices.first(where: { $0.id == deviceId })?.name
                ?? "Simulated Wearable"
            simulateConnection(deviceId: deviceId, deviceName: name)
            return
        }

        guard let peripheral = discoveredPeripherals.first(where: { $0.identifier == deviceId }) else {
            error = "Device no longer available. Tap Scan to refresh."
            return
        }
        connect(to: peripheral)
    }

    /// Connect to a discovered peripheral.
    private func connect(to peripheral: CBPeripheral) {
        stopScanning()
        connectionState = .connecting
        error = nil
        reconnectAttempts = 0
        isAutoReconnecting = false

        centralManager.connect(peripheral, options: nil)
    }

    /// Disconnect from the currently paired peripheral and forget it on disk.
    func disconnect() {
        let nameForAudit = pairedDeviceName ?? "unknown"
        let idForAudit = pairedDeviceId?.uuidString ?? "unknown"

        guard !simulatedMode else {
            simulateDisconnection()
            forgetPairedPeripheral()
            AuditLogger.log(event: .deviceFailover, extra: [
                "action": "manual_unpair",
                "device": nameForAudit,
                "device_id": idForAudit,
                "mode": "simulated",
            ])
            return
        }

        reconnectTimer?.invalidate()
        reconnectTimer = nil
        isAutoReconnecting = false

        if let peripheral = connectedPeripheral {
            centralManager.cancelPeripheralConnection(peripheral)
        }

        connectedPeripheral = nil
        isPaired = false
        pairedDeviceName = nil
        pairedDeviceId = nil
        connectionState = .disconnected
        forgetPairedPeripheral()

        AuditLogger.log(event: .deviceFailover, extra: [
            "action": "manual_unpair",
            "device": nameForAudit,
            "device_id": idForAudit,
        ])
    }

    // MARK: - Persistence

    private func savePairedPeripheral(id: UUID) {
        UserDefaults.standard.set(id.uuidString, forKey: Self.pairedPeripheralIdKey)
    }

    private func forgetPairedPeripheral() {
        UserDefaults.standard.removeObject(forKey: Self.pairedPeripheralIdKey)
    }

    private func loadPairedPeripheralId() -> UUID? {
        guard let raw = UserDefaults.standard.string(forKey: Self.pairedPeripheralIdKey) else {
            return nil
        }
        return UUID(uuidString: raw)
    }

    /// Re-acquire the previously paired peripheral and reconnect silently.
    /// Called when the radio first reports `.poweredOn`.
    private func attemptRestore() {
        guard !simulatedMode else { return }
        guard let savedId = loadPairedPeripheralId() else { return }
        let known = centralManager.retrievePeripherals(withIdentifiers: [savedId])
        guard let peripheral = known.first else { return }

        // Show the saved device in the discovered list so the picker doesn't
        // appear empty if the user pulls up the pairing screen mid-restore.
        connectedPeripheral = peripheral
        pairedDeviceId = peripheral.identifier
        pairedDeviceName = peripheral.name
        connectionState = .connecting

        centralManager.connect(peripheral, options: nil)
    }

    // MARK: - Auto-Reconnect

    /// Attempts to reconnect with exponential backoff (2s, 4s, 8s).
    private func attemptReconnect() {
        guard let peripheral = connectedPeripheral else {
            handleFailover()
            return
        }

        guard reconnectAttempts < maxReconnectAttempts else {
            handleFailover()
            return
        }

        isAutoReconnecting = true
        reconnectAttempts += 1
        connectionState = .connecting

        // Exponential backoff: 2s, 4s, 8s
        let delay = reconnectDelaySeconds * pow(2.0, Double(reconnectAttempts - 1))

        #if DEBUG
        print("[BLE] Reconnect attempt \(reconnectAttempts)/\(maxReconnectAttempts) — delay \(delay)s")
        #endif

        reconnectTimer?.invalidate()
        let peripheralToReconnect = peripheral
        reconnectTimer = Timer.scheduledTimer(
            withTimeInterval: delay,
            repeats: false
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.centralManager.connect(peripheralToReconnect, options: nil)
            }
        }
    }

    /// Called when all reconnection attempts have failed.
    private func handleFailover() {
        isAutoReconnecting = false
        reconnectAttempts = 0
        isPaired = false
        pairedDeviceName = nil
        pairedDeviceId = nil
        connectionState = .failedOver
        connectedPeripheral = nil

        error = "Wearable disconnected. Using device camera."

        AuditLogger.log(
            event: .deviceFailover,
            sessionId: activeSessionId,
            extra: [
                "reason": "ble_reconnect_exhausted",
                "attempts": "\(maxReconnectAttempts)",
                "fallback": "device_camera",
            ]
        )

        let sessionId = activeSessionId ?? "unknown"
        onDeviceFailover?(sessionId)
    }

    /// Attempt recovery after failover — scan for the wearable again.
    /// Call this when the user wants to try reconnecting after the app has
    /// fallen back to the device camera.
    func attemptRecovery() {
        guard connectionState == .failedOver else { return }
        connectionState = .recovering
        reconnectAttempts = 0
        error = nil

        AuditLogger.log(
            event: .deviceFailover,
            sessionId: activeSessionId,
            extra: ["action": "recovery_attempt"]
        )

        startScanning()
    }

    // MARK: - Simulated Mode

    /// Synthetic devices surfaced when running in the iOS Simulator.
    /// UUIDs are stable across launches so re-pair / restore flows behave
    /// like the real radio.
    private static let simulatedCatalog: [BLEDiscoveredDevice] = [
        BLEDiscoveredDevice(
            id: UUID(uuidString: "11111111-1111-4111-8111-111111111111")!,
            name: "Ray-Ban Meta Wayfarer",
            rssi: -52
        ),
        BLEDiscoveredDevice(
            id: UUID(uuidString: "22222222-2222-4222-8222-222222222222")!,
            name: "Aurion Body Cam",
            rssi: -67
        ),
        BLEDiscoveredDevice(
            id: UUID(uuidString: "33333333-3333-4333-8333-333333333333")!,
            name: "Generic BLE Wearable",
            rssi: -78
        ),
    ]

    /// Simulates BLE discovery for development/Simulator testing.
    /// Devices appear progressively (~600ms apart) so the picker animates as
    /// in the real flow.
    private func simulateDiscovery() {
        isScanning = true
        connectionState = .scanning
        error = nil
        discoveredDevices = []

        let catalog = Self.simulatedCatalog
        for (index, device) in catalog.enumerated() {
            let delay = 0.6 + Double(index) * 0.6
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self, self.isScanning else { return }
                if !self.discoveredDevices.contains(where: { $0.id == device.id }) {
                    self.discoveredDevices.append(device)
                }
            }
        }

        // Auto-stop simulated scan once the catalog is exhausted.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6 + Double(catalog.count) * 0.6) { [weak self] in
            guard let self else { return }
            self.isScanning = false
            if self.connectionState == .scanning {
                self.connectionState = .disconnected
            }
        }
    }

    /// Simulates a successful BLE connection.
    private func simulateConnection(deviceId: UUID, deviceName: String) {
        connectionState = .connecting
        // Brief delay so the UI shows a connecting state instead of snapping.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            guard let self else { return }
            self.connectionState = .connected
            self.isPaired = true
            self.pairedDeviceId = deviceId
            self.pairedDeviceName = deviceName
            self.savePairedPeripheral(id: deviceId)

            AuditLogger.log(event: .deviceFailover, extra: [
                "action": "paired",
                "device": deviceName,
                "device_id": deviceId.uuidString,
                "mode": "simulated",
            ])

            #if DEBUG
            print("[BLE] Simulated connection to \(deviceName)")
            #endif
        }
    }

    /// Simulates a BLE disconnection.
    private func simulateDisconnection() {
        isPaired = false
        pairedDeviceName = nil
        pairedDeviceId = nil
        connectionState = .disconnected
    }

    // MARK: - Helpers

    /// Checks if a peripheral name matches a known wearable pattern.
    private func isCompatibleWearable(name: String?) -> Bool {
        guard let name = name?.lowercased() else { return false }
        return Self.nameMatchPatterns.contains { name.contains($0) }
    }

    private func upsertDiscoveredDevice(_ device: BLEDiscoveredDevice) {
        if let idx = discoveredDevices.firstIndex(where: { $0.id == device.id }) {
            discoveredDevices[idx] = device
        } else {
            discoveredDevices.append(device)
        }
    }
}

// MARK: - CBCentralManagerDelegate

extension BLEPairingManager: CBCentralManagerDelegate {

    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            switch central.state {
            case .poweredOn:
                self.bluetoothEnabled = true
                self.error = nil
                // Attempt silent restore now that the radio is up. If the user
                // unpaired previously this is a no-op.
                self.attemptRestore()
            case .poweredOff:
                self.bluetoothEnabled = false
                self.error = "Bluetooth is turned off."
                // Do NOT call disconnect() — that wipes the saved pairing. The
                // user just toggled the radio; we want to reconnect on power-on.
                self.connectionState = .disconnected
                self.isPaired = false
            case .unauthorized:
                self.bluetoothEnabled = false
                self.error = "Bluetooth permission denied. Enable in Settings > Privacy > Bluetooth."
            case .unsupported:
                self.bluetoothEnabled = false
                self.error = "Bluetooth is not supported on this device."
            case .resetting:
                self.bluetoothEnabled = false
                self.error = "Bluetooth is resetting..."
            case .unknown:
                self.bluetoothEnabled = false
            @unknown default:
                self.bluetoothEnabled = false
            }
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        // Snapshot any peripheral state we read off the delegate queue before
        // hopping to the main actor — touching CBPeripheral after the closure
        // returns can deadlock.
        let peripheralName = peripheral.name
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let rssiValue = RSSI.intValue
        let identifier = peripheral.identifier

        Task { @MainActor [weak self] in
            guard let self else { return }

            let matchesServiceUUID = advertisedServices.contains { uuid in
                Self.knownServiceUUIDs.contains(uuid)
            }
            let displayName = peripheralName ?? advertisedName ?? "Unknown Device"
            let matchesName = self.isCompatibleWearable(name: peripheralName)
                || self.isCompatibleWearable(name: advertisedName)

            // Filter out garbage advertisers — only surface peripherals that
            // either match our service UUID OR have a name we recognize. This
            // keeps the picker uncluttered (a phone would otherwise see dozens
            // of unrelated BLE devices in a clinic).
            guard matchesServiceUUID || matchesName else { return }

            self.signalStrength = rssiValue

            if !self.discoveredPeripherals.contains(where: { $0.identifier == identifier }) {
                self.discoveredPeripherals.append(peripheral)
            }
            self.upsertDiscoveredDevice(BLEDiscoveredDevice(
                id: identifier,
                name: displayName,
                rssi: rssiValue
            ))
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        let name = peripheral.name ?? "Wearable"
        let id = peripheral.identifier

        Task { @MainActor [weak self] in
            guard let self else { return }
            self.connectedPeripheral = peripheral
            self.isPaired = true
            self.pairedDeviceName = name
            self.pairedDeviceId = id
            self.connectionState = .connected
            self.isAutoReconnecting = false
            self.reconnectAttempts = 0
            self.error = nil
            self.savePairedPeripheral(id: id)

            AuditLogger.log(event: .deviceFailover, extra: [
                "action": "paired",
                "device": name,
                "device_id": id.uuidString,
            ])

            #if DEBUG
            print("[BLE] Connected to \(name)")
            #endif
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: (any Error)?
    ) {
        let errLocalized = error?.localizedDescription
        let name = peripheral.name ?? "Unknown"

        Task { @MainActor [weak self] in
            guard let self else { return }

            #if DEBUG
            print("[BLE] Disconnected from \(name): \(errLocalized ?? "no error")")
            #endif

            // Unexpected disconnect (error present) → trigger reconnect ladder.
            // Intentional disconnect → already cleaned up by `disconnect()`.
            if errLocalized != nil {
                self.isPaired = false
                self.connectionState = .disconnected
                self.attemptReconnect()
            } else {
                self.isPaired = false
                self.pairedDeviceName = nil
                self.pairedDeviceId = nil
                self.connectionState = .disconnected
                self.connectedPeripheral = nil
            }
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: (any Error)?
    ) {
        let errLocalized = error?.localizedDescription
        let name = peripheral.name ?? "Unknown"

        Task { @MainActor [weak self] in
            guard let self else { return }

            #if DEBUG
            print("[BLE] Failed to connect to \(name): \(errLocalized ?? "unknown")")
            #endif

            if self.isAutoReconnecting {
                self.attemptReconnect()
            } else {
                self.connectionState = .disconnected
                self.error = "Failed to connect to \(name). Try again."
            }
        }
    }
}
