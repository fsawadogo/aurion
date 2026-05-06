import SwiftUI

/// Screen 2 — Biometric consent (separate from app consent).
/// Must explicitly accept — no implicit consent.
///
/// Motion: title and intro stagger in; the consent body itself is
/// deliberately *not* animated so the content reads as authoritative
/// rather than performative. CTAs stagger in last.
struct BiometricConsentView: View {
    let onAccept: () -> Void
    let onBack: () -> Void
    @State private var hasRead = false

    var body: some View {
        VStack(spacing: 24) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Biometric Data Consent")
                        .font(.title2)
                        .fontWeight(.bold)
                        .foregroundColor(.aurionTextPrimary)
                        .aurionStagger(order: 0, baseDelay: 0.05)

                    Text("Please read the following carefully before proceeding.")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .aurionStagger(order: 1)

                    consentText
                        .aurionStagger(order: 2)
                }
                .padding(20)
            }

            Toggle(isOn: $hasRead) {
                Text("I have read and understand the above")
                    .font(.subheadline)
            }
            .tint(.aurionGold)
            .padding(.horizontal, 20)
            .aurionStagger(order: 3)

            VStack(spacing: 12) {
                AurionGoldButton(
                    label: "I Agree — Create Voice Profile",
                    full: true,
                    disabled: !hasRead
                ) {
                    AurionHaptics.notification(.success)
                    AuditLogger.log(event: .biometricConsentConfirmed)
                    onAccept()
                }

                AurionGhostButton(label: "Go Back", full: true) {
                    onBack()
                }
            }
            .padding(.bottom, 24)
            .padding(.horizontal, 20)
            .aurionStagger(order: 4)
        }
    }

    private var consentText: some View {
        Text("""
        Aurion Clinical AI requests your consent to collect and process a short voice recording for the purpose of creating a speaker voice profile.

        **What we collect:** A 30-60 second voice recording read from clinical sentences.

        **How it is used:** The recording is processed entirely on this device to create a voice embedding (a mathematical representation of your voice). This embedding is used during clinical sessions to distinguish your speech from your patient's.

        **Storage:** The voice embedding is stored exclusively in this device's secure Keychain. It is never transmitted to any server.

        **Recording deletion:** The raw voice recording is deleted from device memory immediately after the voice embedding is generated. It is never stored on disk or uploaded.

        **Your rights:** You may delete your voice profile at any time from Settings. You may also re-record your voice profile. Declining does not affect your ability to use Aurion — the system will function without speaker separation.

        This consent is governed by applicable biometric data protection laws including Quebec's Law 25 and PIPEDA.
        """)
        .font(.footnote)
        .foregroundColor(.aurionTextPrimary)
    }
}
