import SwiftUI

/// Step 1 -- Wearable setup (BLE pairing with Ray-Ban Meta glasses).
struct WearableSetupView: View {
    let onComplete: () -> Void
    @State private var isPaired = false
    @State private var isScanning = false

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "eyeglasses")
                .font(.system(size: 72))
                .foregroundColor(.aurionTextPrimary)

            Text("Connect Your Glasses")
                .font(.title)
                .fontWeight(.bold)
                .foregroundColor(.aurionTextPrimary)

            Text("Pair your Ray-Ban Meta Smart Glasses or other capture device via Bluetooth.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            if isScanning && !isPaired {
                // Radar sweep animation
                radarSweepView
                    .frame(height: 120)
                    .transition(AurionTransition.scaleIn)
            }

            VStack(spacing: 16) {
                Button("Scan for Devices") {
                    withAnimation(AurionAnimation.smooth) {
                        isScanning = true
                    }
                    // BLE scanning will be implemented with CoreBluetooth
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                        withAnimation(AurionAnimation.spring) {
                            isPaired = true
                            isScanning = false
                        }
                    }
                }
                .buttonStyle(AurionPrimaryButtonStyle())
                .disabled(isScanning || isPaired)

                Button("Skip -- Use Phone Camera") {
                    onComplete()
                }
                .buttonStyle(AurionSecondaryButtonStyle())
            }

            if isPaired {
                deviceCard
                    .transition(AurionTransition.scaleIn)
                    .onAppear {
                        AurionHaptics.notification(.success)
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                            onComplete()
                        }
                    }
            }

            Spacer()
        }
        .padding(20)
    }

    // MARK: - Radar Sweep Animation

    private var radarSweepView: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .stroke(Color.aurionGold.opacity(0.3), lineWidth: 1.5)
                    .scaleEffect(radarScale(for: index))
                    .opacity(radarOpacity(for: index))
                    .animation(
                        AurionAnimation.pulse.delay(Double(index) * 0.3),
                        value: isScanning
                    )
            }

            Image(systemName: "eyeglasses")
                .font(.system(size: 28))
                .foregroundColor(.aurionGold)
        }
    }

    private func radarScale(for index: Int) -> CGFloat {
        isScanning ? CGFloat(1.0 + Double(index) * 0.4) : 0.5
    }

    private func radarOpacity(for index: Int) -> Double {
        isScanning ? (1.0 - Double(index) * 0.3) : 0.0
    }

    // MARK: - Device Card

    private var deviceCard: some View {
        HStack(spacing: 14) {
            Image(systemName: "eyeglasses")
                .font(.system(size: 24))
                .foregroundColor(.aurionGold)

            VStack(alignment: .leading, spacing: 2) {
                Text("Ray-Ban Meta")
                    .font(.headline)
                    .foregroundColor(.aurionTextPrimary)
                Text("Connected")
                    .font(.caption)
                    .foregroundColor(.green)
            }

            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 22))
                .foregroundColor(.green)
        }
        .aurionCard()
    }
}
