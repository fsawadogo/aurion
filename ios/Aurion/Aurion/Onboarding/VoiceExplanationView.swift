import SwiftUI

/// Screen 1 — Voice enrollment explanation.
/// "Help Aurion recognize your voice"
///
/// Motion: hero icon scales in with a breathing gold halo behind it,
/// title / body / CTAs stagger in over ~600ms. Calm, not chirpy.
struct VoiceExplanationView: View {
    let onGetStarted: () -> Void
    let onSkip: () -> Void

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "waveform.badge.mic")
                .font(.system(size: 72))
                .foregroundColor(.aurionGold)
                .aurionBreathingGlow(radius: 36)
                .aurionStagger(order: 0, baseDelay: 0.05)

            Text("Help Aurion recognize your voice")
                .font(.title)
                .fontWeight(.bold)
                .foregroundColor(.aurionTextPrimary)
                .multilineTextAlignment(.center)
                .aurionStagger(order: 1)

            Text("Aurion uses a short voice sample to separate your observations from your patient's during visits.\n\nYour recording is processed on this device only and deleted immediately. Nothing is sent to our servers.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 20)
                .aurionStagger(order: 2)

            Spacer()

            VStack(spacing: 12) {
                AurionGoldButton(label: "Get Started", full: true) {
                    onGetStarted()
                }
                AurionGhostButton(label: "Skip for now", full: true) {
                    AuditLogger.log(event: .voiceEnrollmentSkipped)
                    onSkip()
                }
            }
            .aurionStagger(order: 3)

            Spacer().frame(height: 40)
        }
        .padding(20)
    }
}
