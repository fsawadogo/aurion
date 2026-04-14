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

// MARK: - BLE Pairing Manager

/// BLE pairing manager for wearable devices (Ray-Ban Meta Smart Glasses).
/// Handles scanning, pairing, connection monitoring, and auto-failover.
///
/// When the glasses disconnect unexpectedly, the manager attempts to reconnect
/// up to 3 times at 2-second intervals. If all attempts fail, it fires the
/// `onDeviceFailover` callback so the app can switch to the iPhone/iPad camera.
///
/// For development/testing without physical glasses, set `simulatedMode = true`.
@MainActor
final class BLEPairingManager: NSObject, ObservableObject {

    // MARK: - Published State

    @Published var isPaired = false
    @Published var isScanning = false
    @Published var pairedDeviceName: String?
    @Published var connectionState: BLEConnectionState = .disconnected
    @Published var bluetoothEnabled = false
    @Published var error: String?

    // MARK: - Callbacks

    /// Called when the glasses fail to reconnect and the system should fall back to the device camera.
    var onDeviceFailover: ((String) -> Void)?

    // MARK: - Configuration

    /// When true, simulates BLE discovery and pairing for Simulator / no-hardware testing.
    var simulatedMode = false

    /// Maximum number of reconnection attempts after unexpected disconnect.
    private let maxReconnectAttempts = 3

    /// Delay between reconnection attempts in seconds.
    private let reconnectDelaySeconds: TimeInterval = 2.0

    /// Timeout for scanning before giving up (seconds).
    private let scanTimeoutSeconds: TimeInterval = 30.0

    // MARK: - Known Ray-Ban Meta BLE Identifiers

    /// Known BLE service UUIDs for Ray-Ban Meta Smart Glasses.
    /// These may change with firmware updates — kept configurable.
    private static let knownServiceUUIDs: [CBUUID] = [
        // Meta companion service — primary pairing UUID
        CBUUID(string: "FE2C1000-8366-4814-8EB0-01DE32100BEA"),
    ]

    /// Fallback name fragments for discovery when service UUIDs are not advertised.
    private static let nameMatchPatterns: [String] = [
        "ray-ban",
        "meta",
        "ray ban",
        "stories",       // Ray-Ban Stories (Gen 1)
        "wayfarer",      // Ray-Ban Meta Wayfarer
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
    }

    // MARK: - Scanning

    /// Start scanning for Ray-Ban Meta glasses or compatible wearables.
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
        isScanning = true
        connectionState = .scanning

        // Scan for known service UUIDs first; also scan broadly to catch name-based matches
        centralManager.scanForPeripherals(
            withServices: nil, // Scan all — we filter in didDiscover
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )

        // Auto-stop scanning after timeout
        scanTimer?.invalidate()
        scanTimer = Timer.scheduledTimer(withTimeInterval: scanTimeoutSeconds, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.isScanning else { return }
                self.stopScanning()
                if !self.isPaired {
                    self.error = "No glasses found. Make sure they are powered on and nearby."
                }
            }
        }
    }

    /// Stop scanning for peripherals.
    func stopScanning() {
        guard !simulatedMode else {
            isScanning = false
            if connectionState == .scanning { connectionState = .disconnected }
            return
        }

        scanTimer?.invalidate()
        scanTimer = nil

        if centralManager.isScanning {
            centralManager.stopScan()
        }
        isScanning = false
        if connectionState == .scanning {
            connectionState = .disconnected
        }
    }

    // MARK: - Connection

    /// Connect to a discovered peripheral.
    func connect(to peripheral: CBPeripheral) {
        guard !simulatedMode else {
            simulateConnection(deviceName: peripheral.name ?? "Simulated Glasses")
            return
        }

        stopScanning()
        connectionState = .connecting
        error = nil
        reconnectAttempts = 0
        isAutoReconnecting = false

        centralManager.connect(peripheral, options: nil)
    }

    /// Disconnect from the currently paired peripheral.
    func disconnect() {
        guard !simulatedMode else {
            simulateDisconnection()
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
        connectionState = .disconnected
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
        connectionState = .failedOver
        connectedPeripheral = nil

        error = "Glasses disconnected. Using device camera."

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

    /// Attempt recovery after failover — scan for glasses again.
    /// Call this when the user wants to try reconnecting to glasses
    /// after the app has fallen back to the device camera.
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

        // Start scanning again
        startScanning()
    }

    // MARK: - Simulated Mode

    /// Simulates BLE discovery for development/Simulator testing.
    private func simulateDiscovery() {
        isScanning = true
        connectionState = .scanning
        error = nil

        // Simulate a short scan delay
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            guard let self else { return }
            self.isScanning = false
            self.simulateConnection(deviceName: "Ray-Ban Meta (Simulated)")
        }
    }

    /// Simulates a successful BLE connection.
    private func simulateConnection(deviceName: String) {
        connectionState = .connected
        isPaired = true
        pairedDeviceName = deviceName

        #if DEBUG
        print("[BLE] Simulated connection to \(deviceName)")
        #endif
    }

    /// Simulates a BLE disconnection.
    private func simulateDisconnection() {
        isPaired = false
        pairedDeviceName = nil
        connectionState = .disconnected
    }

    // MARK: - Helpers

    /// Checks if a peripheral name matches known Ray-Ban Meta patterns.
    private func isRayBanMetaDevice(name: String?) -> Bool {
        guard let name = name?.lowercased() else { return false }
        return Self.nameMatchPatterns.contains { name.contains($0) }
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
            case .poweredOff:
                self.bluetoothEnabled = false
                self.error = "Bluetooth is turned off."
                self.disconnect()
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
        Task { @MainActor [weak self] in
            guard let self else { return }

            // Check if this peripheral matches Ray-Ban Meta by name or advertised services
            let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
            let matchesServiceUUID = advertisedServices.contains { uuid in
                Self.knownServiceUUIDs.contains(uuid)
            }
            let matchesName = self.isRayBanMetaDevice(name: peripheral.name)

            guard matchesServiceUUID || matchesName else { return }

            // Avoid duplicates
            if !self.discoveredPeripherals.contains(where: { $0.identifier == peripheral.identifier }) {
                self.discoveredPeripherals.append(peripheral)

                #if DEBUG
                print("[BLE] Discovered: \(peripheral.name ?? "Unknown") (RSSI: \(RSSI))")
                #endif

                // Auto-connect to the first discovered device
                self.connect(to: peripheral)
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.connectedPeripheral = peripheral
            self.isPaired = true
            self.pairedDeviceName = peripheral.name ?? "Ray-Ban Meta"
            self.connectionState = .connected
            self.isAutoReconnecting = false
            self.reconnectAttempts = 0
            self.error = nil

            #if DEBUG
            print("[BLE] Connected to \(peripheral.name ?? "Unknown")")
            #endif
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: (any Error)?
    ) {
        Task { @MainActor [weak self] in
            guard let self else { return }

            #if DEBUG
            print("[BLE] Disconnected from \(peripheral.name ?? "Unknown"): \(error?.localizedDescription ?? "no error")")
            #endif

            // If this was an unexpected disconnect (error present), attempt reconnect
            if error != nil {
                self.isPaired = false
                self.connectionState = .disconnected
                self.attemptReconnect()
            } else {
                // Intentional disconnect — already handled by disconnect()
                self.isPaired = false
                self.pairedDeviceName = nil
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
        Task { @MainActor [weak self] in
            guard let self else { return }

            #if DEBUG
            print("[BLE] Failed to connect to \(peripheral.name ?? "Unknown"): \(error?.localizedDescription ?? "unknown")")
            #endif

            if self.isAutoReconnecting {
                // Part of a reconnection sequence — try again
                self.attemptReconnect()
            } else {
                self.connectionState = .disconnected
                self.error = "Failed to connect to \(peripheral.name ?? "glasses"). Try again."
            }
        }
    }
}
