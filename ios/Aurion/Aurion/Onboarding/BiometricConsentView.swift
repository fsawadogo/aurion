import SwiftUI

/// Screen 2 -- Biometric consent (separate from app consent).
/// Must explicitly accept -- no implicit consent.
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

                    Text("Please read the following carefully before proceeding.")
                        .font(.subheadline)
                        .foregroundColor(.secondary)

                    consentText
                }
                .padding(20)
            }

            Toggle(isOn: $hasRead) {
                Text("I have read and understand the above")
                    .font(.subheadline)
            }
            .padding(.horizontal, 20)

            VStack(spacing: 12) {
                Button("I Agree -- Create Voice Profile") {
                    AurionHaptics.notification(.success)
                    AuditLogger.log(event: .biometricConsentConfirmed)
                    onAccept()
                }
                .buttonStyle(AurionPrimaryButtonStyle())
                .disabled(!hasRead)
                .opacity(hasRead ? 1.0 : 0.5)

                Button("Go Back") {
                    onBack()
                }
                .buttonStyle(AurionSecondaryButtonStyle())
            }
            .padding(.bottom, 24)
            .padding(.horizontal, 20)
        }
    }

    private var consentText: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("""
            Aurion Clinical AI requests your consent to collect and process a short voice recording for the purpose of creating a speaker voice profile.

            **What we collect:** A 30-60 second voice recording read from clinical sentences.

            **How it is used:** The recording is processed entirely on this device to create a voice embedding (a mathematical representation of your voice). This embedding is used during clinical sessions to distinguish your speech from your patient's.

            **Storage:** The voice embedding is stored exclusively in this device's secure Keychain. It is never transmitted to any server.

            **Recording deletion:** The raw voice recording is deleted from device memory immediately after the voice embedding is generated. It is never stored on disk or uploaded.

            **Your rights:** You may delete your voice profile at any time from Settings. You may also re-record your voice profile. Declining does not affect your ability to use Aurion -- the system will function without speaker separation.

            This consent is governed by applicable biometric data protection laws including Quebec's Law 25 and PIPEDA.
            """)
            .font(.footnote)
            .foregroundColor(.aurionTextPrimary)
        }
    }
}
