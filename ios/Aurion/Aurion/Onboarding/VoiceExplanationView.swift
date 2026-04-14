import SwiftUI

/// Screen 1 -- Voice enrollment explanation.
/// "Help Aurion recognize your voice"
struct VoiceExplanationView: View {
    let onGetStarted: () -> Void
    let onSkip: () -> Void

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "waveform.badge.mic")
                .font(.system(size: 72))
                .foregroundColor(Color.aurionGold)

            Text("Help Aurion recognize your voice")
                .font(.title)
                .fontWeight(.bold)
                .foregroundColor(.aurionTextPrimary)
                .multilineTextAlignment(.center)

            Text("Aurion uses a short voice sample to separate your observations from your patient's during visits.\n\nYour recording is processed on this device only and deleted immediately. Nothing is sent to our servers.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 20)

            Spacer()

            VStack(spacing: 16) {
                Button("Get started") {
                    onGetStarted()
                }
                .buttonStyle(AurionPrimaryButtonStyle())

                Button("Skip for now") {
                    // Log voice_enrollment_skipped to audit trail
                    AuditLogger.log(event: .voiceEnrollmentSkipped)
                    onSkip()
                }
                .buttonStyle(AurionSecondaryButtonStyle())
            }

            Spacer().frame(height: 40)
        }
        .padding(20)
    }
}
