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
    /// Gates the "I have read and understand" toggle. The consent body must be
    /// scrolled to the end before the physician can attest — this is a
    /// legal/compliance artifact, so we don't let anyone confirm a consent
    /// they demonstrably haven't seen (#300). Latches true once the bottom
    /// sentinel appears and never flips back (scrolling up shouldn't re-lock).
    @State private var hasScrolledToBottom = false

    /// Named coordinate space the bottom sentinel reports its position in.
    private let scrollSpace = "biometricConsentScroll"

    var body: some View {
        VStack(spacing: 24) {
            GeometryReader { outer in
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

                        // Bottom sentinel — reports its maxY in the scroll
                        // coordinate space so we can detect when the consent
                        // body has been read all the way to the end. A short
                        // body that fits without scrolling reports immediately,
                        // unlocking the toggle right away (nothing to scroll).
                        Color.clear
                            .frame(height: 1)
                            .background(
                                GeometryReader { proxy in
                                    Color.clear.preference(
                                        key: ConsentScrollBottomKey.self,
                                        value: proxy.frame(in: .named(scrollSpace)).maxY
                                    )
                                }
                            )
                            .accessibilityHidden(true)
                    }
                    .padding(20)
                }
                .coordinateSpace(name: scrollSpace)
                .onPreferenceChange(ConsentScrollBottomKey.self) { maxY in
                    // Sentinel's bottom edge has entered (or passed) the
                    // visible viewport → the body has been fully scrolled.
                    if maxY <= outer.size.height + 1 {
                        hasScrolledToBottom = true
                    }
                }
            }

            if !hasScrolledToBottom {
                // Quiet nudge until the body has been read to the end.
                HStack(spacing: 6) {
                    Image(systemName: "arrow.down")
                        .font(.system(size: 12, weight: .semibold))
                    Text(L("onboarding.biometric.scrollHint"))
                        .font(.caption)
                }
                .foregroundColor(.aurionTextSecondary)
                .padding(.horizontal, 20)
                .transition(.opacity)
                .accessibilityHint(L("onboarding.biometric.scrollA11yHint"))
            }

            Toggle(isOn: $hasRead) {
                Text(L("onboarding.biometric.read"))
                    .font(.subheadline)
            }
            .tint(.aurionGold)
            .disabled(!hasScrolledToBottom)
            .opacity(hasScrolledToBottom ? 1 : 0.5)
            .padding(.horizontal, 20)
            .aurionStagger(order: 3)
            .animation(AurionAnimation.smooth, value: hasScrolledToBottom)

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

/// Carries the consent body's bottom-edge position (maxY in the scroll
/// coordinate space) up to the gate that unlocks the "I have read" toggle.
private struct ConsentScrollBottomKey: PreferenceKey {
    static var defaultValue: CGFloat = .greatestFiniteMagnitude
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}
