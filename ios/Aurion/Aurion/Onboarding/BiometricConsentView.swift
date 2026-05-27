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
                    Text(L("onboarding.biometric.title"))
                        .font(.title2)
                        .fontWeight(.bold)
                        .foregroundColor(.aurionTextPrimary)
                        .aurionStagger(order: 0, baseDelay: 0.05)

                    Text(L("onboarding.biometric.sub"))
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .aurionStagger(order: 1)

                    consentText
                        .aurionStagger(order: 2)
                }
                .padding(20)
            }

            Toggle(isOn: $hasRead) {
                Text(L("onboarding.biometric.read"))
                    .font(.subheadline)
            }
            .tint(.aurionGold)
            .padding(.horizontal, 20)
            .aurionStagger(order: 3)

            VStack(spacing: 12) {
                AurionGoldButton(
                    label: L("onboarding.biometric.agree"),
                    full: true,
                    disabled: !hasRead
                ) {
                    AurionHaptics.notification(.success)
                    AuditLogger.log(event: .biometricConsentConfirmed)
                    onAccept()
                }

                AurionGhostButton(label: L("onboarding.biometric.goBack"), full: true) {
                    onBack()
                }
            }
            .padding(.bottom, 24)
            .padding(.horizontal, 20)
            .aurionStagger(order: 4)
        }
    }

    private var consentText: some View {
        // Localized markdown — `**bold**` labels + blank-line paragraph
        // breaks. `Text(String)` renders verbatim (no markdown), so parse
        // through AttributedString to keep the bold section headers while
        // preserving paragraph whitespace.
        let raw = L("onboarding.biometric.consentText")
        let attributed = (try? AttributedString(
            markdown: raw,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(raw)
        return Text(attributed)
            .font(.footnote)
            .foregroundColor(.aurionTextPrimary)
    }
}
