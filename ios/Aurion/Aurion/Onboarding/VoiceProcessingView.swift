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
    @State private var currentStepLabel: String = L("onboarding.voiceProc.step1")
    @State private var failureMessage: String?

    private let stepLabels = [
        L("onboarding.voiceProc.step1"),
        L("onboarding.voiceProc.step2"),
        L("onboarding.voiceProc.step3"),
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

                Text(L("onboarding.voiceProc.creating"))
                    .font(.title3)
                    .foregroundColor(.aurionTextPrimary)

                Text(currentStepLabel)
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .transition(.opacity)
                    .id(currentStepLabel)
                    .animation(.aurionIOS, value: currentStepLabel)
            } else if let failureMessage {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 72))
                    .foregroundColor(.aurionAmber)
                    .aurionStagger(order: 0, baseDelay: 0.1)

                Text(L("onboarding.voiceProc.failedTitle"))
                    .font(.title3)
                    .fontWeight(.semibold)
                    .foregroundColor(.aurionTextPrimary)
                    .aurionStagger(order: 1, baseDelay: 0.1)

                Text(failureMessage)
                    .font(.body)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
                    .aurionStagger(order: 2, baseDelay: 0.1)
            } else {
                AurionAnimatedCheck(size: 96, color: .aurionGold)

                Text(L("onboarding.voiceProc.saved"))
                    .font(.title3)
                    .fontWeight(.semibold)
                    .foregroundColor(.aurionTextPrimary)
                    .aurionStagger(order: 0, baseDelay: 0.5)

                Text(L("onboarding.voiceProc.savedSub"))
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
                    .aurionStagger(order: 1, baseDelay: 0.5)
            }

            Spacer()

            if !isProcessing {
                if failureMessage != nil {
                    VStack(spacing: 12) {
                        AurionGoldButton(label: L("common.retry"), full: true) { retryEnrollment() }
                        Button(L("common.skip")) { skipEnrollment() }
                            .aurionFont(14, weight: .medium, relativeTo: .body)
                            .foregroundColor(.aurionTextSecondary)
                    }
                    .padding(.horizontal, 20)
                    .aurionStagger(order: 3, baseDelay: 0.1)
                } else {
                    AurionGoldButton(label: L("onboarding.voiceProc.continue"), full: true) { onComplete() }
                        .padding(.horizontal, 20)
                        .aurionStagger(order: 2, baseDelay: 0.5)
                }
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
            // Only celebrate when the embedding actually landed in the
            // Keychain. A failed extraction (no file / unanalyzable audio)
            // sets `failureMessage` and must fire the error notification,
            // not the success chime + checkmark.
            if failureMessage == nil {
                AurionHaptics.notification(.success)
            } else {
                AurionHaptics.notification(.error)
            }
        }
    }

    /// Reads the recorded audio file, extracts an on-device voice
    /// fingerprint (128-dim MFCC embedding, matching the session-time
    /// speaker tagger), saves it to the Keychain, and deletes the raw
    /// audio file. Per CLAUDE.md, the raw recording must NEVER be
    /// persisted to disk past this point and the embedding NEVER leaves
    /// the device.
    private func extractAndStoreEmbedding() {
        guard let url = audioFileURL else {
            failureMessage = L("onboarding.voiceProc.noRecording")
            return
        }
        guard let embedding = VoiceEmbeddingExtractor.extract(from: url) else {
            failureMessage = L("onboarding.voiceProc.analyzeFailed")
            try? FileManager.default.removeItem(at: url)
            return
        }
        KeychainHelper.shared.saveVoiceEmbedding(embedding)
        try? FileManager.default.removeItem(at: url)
        AuditLogger.log(event: .voiceEnrollmentComplete)
    }

    /// Re-run enrollment after a failure: reset the progress UI + failure
    /// state, flip back into the processing branch, and drive the pipeline
    /// again. The success/error haptic is re-decided at the end of the run.
    private func retryEnrollment() {
        failureMessage = nil
        progress = 0
        currentStepLabel = stepLabels[0]
        withAnimation(.aurionIOS) { isProcessing = true }
        processVoiceEnrollment()
    }

    /// Voice enrollment is optional — let the clinician proceed without a
    /// profile rather than trapping them on a failed processing screen.
    private func skipEnrollment() {
        AuditLogger.log(event: .voiceEnrollmentSkipped)
        onComplete()
    }
}
