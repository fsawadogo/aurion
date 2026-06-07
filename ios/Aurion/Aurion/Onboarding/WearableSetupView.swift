import SwiftUI

/// Step 1 — Wearable setup (BLE pairing with Ray-Ban Meta glasses or any
/// compatible Bluetooth capture wearable).
///
/// Wires `BLEPairingManager.shared` to a SwiftUI picker: tapping Scan starts a
/// real BLE scan (or simulated discovery on the iOS Simulator), discovered
/// devices appear progressively, and the clinician taps to pair. On success
/// the paired peripheral UUID is persisted so the next launch reconnects
/// silently.
struct WearableSetupView: View {
    let onComplete: () -> Void
    @StateObject private var ble = BLEPairingManager.shared
    @State private var didFireSuccessHaptic = false

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 12)

            heroIcon
                .aurionStagger(order: 0, baseDelay: 0.05)

            Text(L("onboarding.wearable.title"))
                .font(.title)
                .fontWeight(.bold)
                .foregroundColor(.aurionTextPrimary)
                .aurionStagger(order: 1)

            Text(L("onboarding.wearable.sub"))
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
                .aurionStagger(order: 2)

            // Discovered devices appear here. Empty until Scan tapped.
            if !ble.isPaired {
                discoveredList
                    .aurionStagger(order: 3)
            }

            VStack(spacing: 12) {
                if !ble.isPaired {
                    AurionGoldButton(
                        label: scanButtonLabel,
                        full: true,
                        disabled: ble.isScanning || ble.connectionState == .connecting
                    ) {
                        ble.startScanning()
                    }
                }
                AurionGhostButton(label: L("onboarding.wearable.skip"), full: true) {
                    onComplete()
                }
            }
            .aurionStagger(order: 4)

            if ble.isPaired {
                VStack(spacing: 12) {
                    pairedCard
                    // Explicit Continue instead of a timed auto-advance:
                    // gives the clinician a beat to confirm the device name
                    // shown in pairedCard (and to re-scan if the wrong
                    // nearby device was tapped) before leaving the screen.
                    AurionGoldButton(label: L("setup.continue"), full: true) {
                        onComplete()
                    }
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .onAppear { handlePairedAppearance() }
            }

            if let err = ble.error, !ble.isPaired {
                Text(err)
                    .font(.caption)
                    .foregroundColor(.aurionRed)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
                    .transition(.opacity)
            }

            Spacer(minLength: 12)
        }
        .padding(20)
        .animation(.aurionIOS, value: ble.isPaired)
        .animation(.aurionIOS, value: ble.discoveredDevices)
        .animation(.aurionIOS, value: ble.isScanning)
    }

    // MARK: - Hero icon

    @ViewBuilder
    private var heroIcon: some View {
        if ble.isScanning && !ble.isPaired {
            AurionRadarPulse(color: .aurionGold) {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 40))
                    .foregroundColor(.aurionGold)
            }
            .frame(height: 200)
        } else if ble.isPaired {
            Image(systemName: "eyeglasses")
                .font(.system(size: 72))
                .foregroundColor(.aurionGold)
                .scaleEffect(1.05)
                .aurionBreathingGlow(radius: 36)
        } else {
            Image(systemName: "eyeglasses")
                .font(.system(size: 72))
                .foregroundColor(.aurionTextPrimary)
                .aurionBreathingGlow(color: .aurionNavy, radius: 24)
        }
    }

    // MARK: - Device list (during/after scan, before pairing)

    @ViewBuilder
    private var discoveredList: some View {
        if !ble.discoveredDevices.isEmpty {
            VStack(spacing: 8) {
                ForEach(ble.discoveredDevices) { device in
                    deviceRow(device)
                }
            }
            .padding(.horizontal, 4)
        } else if ble.isScanning {
            Text(L("onboarding.wearable.scanning"))
                .font(.caption)
                .foregroundColor(.aurionTextSecondary)
        }
    }

    private func deviceRow(_ device: BLEDiscoveredDevice) -> some View {
        let isConnecting = ble.connectionState == .connecting
            && ble.pairedDeviceId == device.id
        return Button {
            AurionHaptics.selection()
            ble.connect(deviceId: device.id)
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 20))
                    .foregroundColor(.aurionGold)
                VStack(alignment: .leading, spacing: 2) {
                    Text(device.name)
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                        .lineLimit(1)
                    Text(rssiLabel(device.rssi))
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(.aurionTextSecondary)
                }
                Spacer(minLength: 0)
                if isConnecting {
                    ProgressView().scaleEffect(0.8)
                } else {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.aurionTextSecondary)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.aurionCardBackground)
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .disabled(isConnecting)
    }

    private func rssiLabel(_ rssi: Int) -> String {
        let strength: String
        switch rssi {
        case ..<(-80): strength = L("onboarding.wearable.signalWeak")
        case (-80)..<(-65): strength = L("onboarding.wearable.signalFair")
        default: strength = L("onboarding.wearable.signalStrong")
        }
        return L("onboarding.wearable.signalFormat", strength, rssi)
    }

    // MARK: - Paired Card

    private var pairedCard: some View {
        AurionCard(padding: 16) {
            HStack(spacing: 14) {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 24))
                    .foregroundColor(.aurionGold)
                VStack(alignment: .leading, spacing: 2) {
                    Text(ble.pairedDeviceName ?? L("onboarding.wearable.deviceFallback"))
                        .font(.headline)
                        .foregroundColor(.aurionTextPrimary)
                    Text(L("onboarding.wearable.connected"))
                        .font(.caption)
                        .foregroundColor(.aurionGreen)
                }
                Spacer()
                AurionStatusPill(kind: .done, labelOverride: L("onboarding.wearable.paired"))
            }
        }
    }

    // MARK: - Helpers

    private var scanButtonLabel: String {
        if ble.isScanning { return L("onboarding.wearable.scanningShort") }
        if ble.discoveredDevices.isEmpty { return L("onboarding.wearable.scan") }
        return L("onboarding.wearable.scanAgain")
    }

    /// Fire the success haptic exactly once when the paired card appears.
    /// Advancing is now driven by the explicit Continue button rather than
    /// a timer, so the clinician confirms the device before moving on.
    private func handlePairedAppearance() {
        guard !didFireSuccessHaptic else { return }
        didFireSuccessHaptic = true
        AurionHaptics.notification(.success)
    }
}
