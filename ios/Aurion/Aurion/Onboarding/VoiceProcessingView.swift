import SwiftUI

/// Screen 4 -- Processing and confirmation.
/// Generates voice embedding, deletes raw audio, stores in Keychain.
struct VoiceProcessingView: View {
    let onComplete: () -> Void
    @State private var isProcessing = true
    @State private var isComplete = false
    @State private var progress: Double = 0
    @State private var currentStepLabel: String = "Analyzing voice patterns..."

    private let stepLabels = [
        "Analyzing voice patterns...",
        "Generating voice embedding...",
        "Securing in Keychain..."
    ]

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            if isProcessing {
                // Progress ring with percentage
                ZStack {
                    CircularProgressRing(
                        progress: progress,
                        color: .aurionGold,
                        lineWidth: 6,
                        size: 100
                    )

                    Text("\(Int(progress * 100))%")
                        .font(.title3)
                        .monospacedDigit()
                        .fontWeight(.semibold)
                        .foregroundColor(.aurionTextPrimary)
                }

                Text("Creating your voice profile...")
                    .font(.title3)
                    .foregroundColor(.aurionTextPrimary)

                // Rotating step labels
                Text(currentStepLabel)
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .transition(.opacity)
                    .id(currentStepLabel)
                    .animation(AurionAnimation.smooth, value: currentStepLabel)

            } else {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 80))
                    .foregroundColor(.aurionGold)
                    .transition(AurionTransition.scaleIn)

                Text("Voice profile saved to this device")
                    .font(.title3)
                    .fontWeight(.semibold)
                    .foregroundColor(.aurionTextPrimary)

                Text("You can update or delete your voice profile anytime in Settings.")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
            }

            Spacer()

            if !isProcessing {
                Button("Continue to Dashboard") {
                    onComplete()
                }
                .buttonStyle(AurionPrimaryButtonStyle())
            }

            Spacer().frame(height: 40)
        }
        .padding(20)
        .onAppear {
            processVoiceEnrollment()
        }
    }

    private func processVoiceEnrollment() {
        // In real implementation:
        // 1. Pass audio buffer to SpeechBrain/Apple speaker model
        // 2. Generate 256-dim voice embedding
        // 3. Delete raw audio buffer from memory IMMEDIATELY
        // 4. Store embedding in Keychain
        // 5. Write audit event (no embedding data)

        // Animate progress from 0 to 1 over ~1.5s
        let totalDuration: Double = 1.5
        let steps = 30
        let interval = totalDuration / Double(steps)

        for i in 1...steps {
            DispatchQueue.main.asyncAfter(deadline: .now() + interval * Double(i)) {
                withAnimation(AurionAnimation.smooth) {
                    progress = Double(i) / Double(steps)
                }

                // Cycle through step labels at progress milestones
                if i == 1 {
                    currentStepLabel = stepLabels[0]
                } else if i == steps / 3 {
                    withAnimation(AurionAnimation.smooth) {
                        currentStepLabel = stepLabels[1]
                    }
                } else if i == (steps * 2) / 3 {
                    withAnimation(AurionAnimation.smooth) {
                        currentStepLabel = stepLabels[2]
                    }
                }
            }
        }

        // Complete processing after animation finishes
        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration + 0.2) {
            // Simulate embedding generation
            let mockEmbedding = Data(repeating: 0, count: 256 * 4) // 256 floats
            KeychainHelper.shared.saveVoiceEmbedding(mockEmbedding)

            // Raw audio is deleted -- never stored to disk
            // Only timestamp and device ID logged -- no embedding data
            AuditLogger.log(event: .voiceEnrollmentComplete)

            withAnimation(AurionAnimation.smooth) {
                isProcessing = false
                isComplete = true
            }
            AurionHaptics.notification(.success)
        }
    }
}
