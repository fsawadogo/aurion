import SwiftUI
import AVFoundation
import ReplayKit
@preconcurrency import CoreBluetooth

/// Device management hub — 4th tab.
/// Shows all capture devices, permissions, and scanning controls.
struct DeviceHubView: View {
    @StateObject private var bleManager = BLEPairingManager()
    @StateObject private var captureManager = CaptureManager()
    @State private var isScanning = false
    @State private var showTestCapture = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // ── Active Capture Device ─────────────────
                    activeDeviceCard

                    // ── Permissions Grid ──────────────────────
                    VStack(alignment: .leading, spacing: 12) {
                        Text("PERMISSIONS")
                            .aurionSectionHeader()
                        permissionsGrid
                    }

                    // ── Connected Devices ─────────────────────
                    VStack(alignment: .leading, spacing: 12) {
                        Text("DEVICES")
                            .aurionSectionHeader()
                        devicesList
                    }

                    // ── Device Actions ────────────────────────
                    VStack(spacing: 12) {
                        Button {
                            AurionHaptics.impact(.medium)
                            startScan()
                        } label: {
                            HStack {
                                Image(systemName: "antenna.radiowaves.left.and.right")
                                Text(isScanning ? "Scanning..." : "Scan for Devices")
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(AurionPrimaryButtonStyle())
                        .disabled(isScanning)

                        Button {
                            showTestCapture = true
                        } label: {
                            HStack {
                                Image(systemName: "checkmark.circle")
                                Text("Test Capture")
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(AurionSecondaryButtonStyle())
                    }
                    .padding(.top, 8)
                }
                .padding(20)
            }
            .background(Color.aurionBackground)
            .navigationTitle("Devices")
            .aurionNavBar()
            .onAppear { captureManager.checkPermissions() }
            .alert("Test Capture", isPresented: $showTestCapture) {
                Button("Run Test") {
                    AurionHaptics.impact(.light)
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This will run a 3-second test recording to verify camera, microphone, and screen capture are working.")
            }
        }
    }

    // MARK: - Active Device Card

    private var activeDeviceCard: some View {
        VStack(spacing: 16) {
            ZStack {
                // Pulse ring when connected
                if bleManager.connectionState == .connected {
                    Circle()
                        .stroke(Color.green.opacity(0.3), lineWidth: 2)
                        .frame(width: 80, height: 80)
                        .scaleEffect(1.2)
                        .opacity(0.5)
                        .animation(AurionAnimation.pulse, value: bleManager.isPaired)
                }

                Circle()
                    .fill(activeDeviceColor.opacity(0.1))
                    .frame(width: 72, height: 72)

                Image(systemName: activeDeviceIcon)
                    .font(.system(size: 32))
                    .foregroundColor(activeDeviceColor)
            }

            Text(activeDeviceName)
                .font(.headline)
                .foregroundColor(.aurionTextPrimary)

            Text(activeDeviceStatus)
                .font(.caption)
                .foregroundColor(activeDeviceColor)

            // Signal strength for BLE devices
            if bleManager.connectionState == .connected {
                signalStrengthBars
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity)
        .background(Color.aurionCardBackground)
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(activeDeviceColor.opacity(0.2), lineWidth: 1)
        )
    }

    private var activeDeviceName: String {
        if bleManager.connectionState == .connected {
            return bleManager.pairedDeviceName ?? "Ray-Ban Meta"
        }
        return "iPhone Camera"
    }

    private var activeDeviceIcon: String {
        bleManager.connectionState == .connected ? "eyeglasses" : "camera.fill"
    }

    private var activeDeviceColor: Color {
        switch bleManager.connectionState {
        case .connected: return .green
        case .scanning, .connecting, .recovering: return .aurionGold
        case .failedOver: return .aurionAmber
        case .disconnected: return .secondary
        }
    }

    private var activeDeviceStatus: String {
        switch bleManager.connectionState {
        case .connected: return "Connected — Ready to capture"
        case .scanning: return "Scanning for devices..."
        case .connecting: return "Connecting..."
        case .recovering: return "Reconnecting..."
        case .failedOver: return "Glasses lost — using iPhone camera"
        case .disconnected: return "Using device camera"
        }
    }

    private var signalStrengthBars: some View {
        HStack(spacing: 3) {
            ForEach(0..<4, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(i < signalBars ? Color.green : Color.secondary.opacity(0.2))
                    .frame(width: 4, height: CGFloat(8 + i * 4))
            }
        }
    }

    private var signalBars: Int {
        let rssi = bleManager.signalStrength
        if rssi > -50 { return 4 }
        if rssi > -65 { return 3 }
        if rssi > -80 { return 2 }
        if rssi > -95 { return 1 }
        return 0
    }

    // MARK: - Permissions Grid

    private var permissionsGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            permissionCard(
                icon: "camera.fill",
                label: "Camera",
                granted: captureManager.cameraPermission == .authorized
            )
            permissionCard(
                icon: "mic.fill",
                label: "Microphone",
                granted: captureManager.microphonePermission == .authorized
            )
            permissionCard(
                icon: "antenna.radiowaves.left.and.right",
                label: "Bluetooth",
                granted: bleManager.bluetoothEnabled
            )
            permissionCard(
                icon: "rectangle.on.rectangle",
                label: "Screen Recording",
                granted: RPScreenRecorder.shared().isAvailable
            )
        }
    }

    private func permissionCard(icon: String, label: String, granted: Bool) -> some View {
        Button {
            if !granted {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
        } label: {
            VStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundColor(granted ? .green : .red)
                Text(label)
                    .font(.caption)
                    .foregroundColor(.aurionTextPrimary)
                Image(systemName: granted ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.caption)
                    .foregroundColor(granted ? .green : .red)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .background(Color.aurionCardBackground)
            .cornerRadius(12)
        }
        .buttonStyle(.plain)
    }

    // MARK: - Devices List

    private var devicesList: some View {
        VStack(spacing: 8) {
            // Glasses
            DeviceStatusCard(
                icon: "eyeglasses",
                name: bleManager.pairedDeviceName ?? "Ray-Ban Meta",
                status: bleDeviceStatus,
                subtitle: bleSubtitle,
                onForget: bleManager.isPaired ? { bleManager.disconnect() } : nil
            )

            // iPhone Camera (always available)
            DeviceStatusCard(
                icon: "camera.fill",
                name: UIDevice.current.name,
                status: captureManager.cameraPermission == .authorized ? .connected : .unavailable,
                subtitle: captureManager.cameraPermission == .authorized ? "Built-in camera ready" : "Permission denied"
            )

            // Microphone
            DeviceStatusCard(
                icon: "mic.fill",
                name: "Microphone",
                status: captureManager.microphonePermission == .authorized ? .connected : .unavailable,
                subtitle: captureManager.microphonePermission == .authorized ? "Built-in microphone ready" : "Permission denied"
            )

            // Screen Recording
            DeviceStatusCard(
                icon: "rectangle.on.rectangle",
                name: "Screen Capture",
                status: RPScreenRecorder.shared().isAvailable ? .connected : .unavailable,
                subtitle: RPScreenRecorder.shared().isAvailable ? "ReplayKit available" : "Not available on this device"
            )

            // Scanning results
            if isScanning {
                HStack {
                    ProgressView()
                    Text("Scanning for nearby devices...")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .padding(.vertical, 12)
            }
        }
    }

    private var bleDeviceStatus: DeviceStatus {
        switch bleManager.connectionState {
        case .connected: return .connected
        case .scanning, .connecting: return .scanning
        case .recovering: return .recovering
        case .failedOver, .disconnected: return .disconnected
        }
    }

    private var bleSubtitle: String {
        switch bleManager.connectionState {
        case .connected: return "Signal: \(bleManager.signalStrength) dBm"
        case .scanning: return "Searching..."
        case .connecting: return "Pairing..."
        case .recovering: return "Reconnecting..."
        case .failedOver: return "Connection lost"
        case .disconnected: return "Not paired"
        }
    }

    // MARK: - Actions

    private func startScan() {
        isScanning = true
        bleManager.startScanning()
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
            isScanning = false
            bleManager.stopScanning()
        }
    }
}
