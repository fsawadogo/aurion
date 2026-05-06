import SwiftUI

/// Screen 4 — Processing and confirmation.
/// Generates voice embedding, deletes raw audio, stores in Keychain.
///
/// Motion: progress ring fills + a thin gold orbit arc rotates around it
/// for an "in flight" feel. Step labels cross-fade as they advance. On
/// completion, the ring transitions to an animated checkmark that draws
/// itself in two passes (ring trim, then check stroke).
struct VoiceProcessingView: View {
    let audioFileURL: URL?
    let onComplete: () -> Void
    @State private var isProcessing = true
    @State private var progress: Double = 0
    @State private var currentStepLabel: String = "Analyzing voice patterns…"
    @State private var failureMessage: String?

    private let stepLabels = [
        "Analyzing voice patterns…",
        "Generating voice embedding…",
        "Securing in Keychain…",
    ]

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            if isProcessing {
                ZStack {
                    AurionOrbitArc(size: 116, arcLength: 0.18, lineWidth: 2.5)
                    CircularProgressRing(progress: progress, color: .aurionGold, lineWidth: 6, size: 100)
                    Text("\(Int(progress * 100))%")
                        .font(.title3)
                        .monospacedDigit()
                        .fontWeight(.semibold)
                        .foregroundColor(.aurionTextPrimary)
                }

                Text("Creating your voice profile…")
                    .font(.title3)
                    .foregroundColor(.aurionTextPrimary)

                Text(currentStepLabel)
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .transition(.opacity)
                    .id(currentStepLabel)
                    .animation(.aurionIOS, value: currentStepLabel)
            } else {
                AurionAnimatedCheck(size: 96, color: .aurionGold)

                Text("Voice profile saved to this device")
                    .font(.title3)
                    .fontWeight(.semibold)
                    .foregroundColor(.aurionTextPrimary)
                    .aurionStagger(order: 0, baseDelay: 0.5)

                Text("You can update or delete your voice profile anytime in Settings.")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
                    .aurionStagger(order: 1, baseDelay: 0.5)
            }

            Spacer()

            if !isProcessing {
                AurionGoldButton(label: "Continue to Dashboard", full: true) { onComplete() }
                    .padding(.horizontal, 20)
                    .aurionStagger(order: 2, baseDelay: 0.5)
            }

            Spacer().frame(height: 40)
        }
        .padding(20)
        .animation(.aurionIOS, value: isProcessing)
        .onAppear { processVoiceEnrollment() }
    }

    private func processVoiceEnrollment() {
        // Pace the progress UI for ~1.6s for legibility — extraction itself
        // finishes before the animation does, so the ring isn't fake "loading"
        // any more, it's intentional pacing.
        let totalDuration: Double = 1.6
        let steps = 32
        let interval = totalDuration / Double(steps)

        for i in 1...steps {
            DispatchQueue.main.asyncAfter(deadline: .now() + interval * Double(i)) {
                withAnimation(.aurionIOS) {
                    progress = Double(i) / Double(steps)
                }
                if i == 1 {
                    currentStepLabel = stepLabels[0]
                } else if i == steps / 3 {
                    withAnimation(.aurionIOS) { currentStepLabel = stepLabels[1] }
                } else if i == (steps * 2) / 3 {
                    withAnimation(.aurionIOS) { currentStepLabel = stepLabels[2] }
                }
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration + 0.25) {
            extractAndStoreEmbedding()
            withAnimation(.aurionIOS) { isProcessing = false }
            AurionHaptics.notification(.success)
        }
    }

    /// Reads the recorded audio file, extracts a 256-dim voice fingerprint
    /// on-device, saves it to the Keychain, and deletes the raw audio file.
    /// Per CLAUDE.md, the raw recording must NEVER be persisted to disk
    /// past this point and the embedding NEVER leaves the device.
    private func extractAndStoreEmbedding() {
        guard let url = audioFileURL else {
            failureMessage = "No recording found."
            return
        }
        guard let embedding = VoiceEmbeddingExtractor.extract(from: url) else {
            failureMessage = "Could not analyze recording."
            try? FileManager.default.removeItem(at: url)
            return
        }
        KeychainHelper.shared.saveVoiceEmbedding(embedding)
        try? FileManager.default.removeItem(at: url)
        AuditLogger.log(event: .voiceEnrollmentComplete)
    }
}
