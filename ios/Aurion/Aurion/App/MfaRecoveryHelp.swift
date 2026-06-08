import SwiftUI

/// Support / account-recovery contact for a clinician who has lost access to
/// their authenticator app.
///
/// TOTP is self-service to *use* but not to *reset*: only a clinic
/// administrator (or Aurion support) can clear the enrolled secret
/// server-side, so the recovery path is deliberately "contact a human"
/// rather than an in-app self-reset (which would defeat the second factor).
enum MfaRecovery {
    /// Shown to the clinician and used as the `mailto:` target. Kept in one
    /// place so the support alias is trivially swappable before the pilot.
    static let supportEmail = "support@aurionclinical.com"
}

/// Low-key "Can't access your code?" affordance for the MFA screens.
///
/// A clinician who loses their authenticator could previously only Cancel
/// back to the login screen with no path forward. This presents a sheet with
/// recovery guidance plus a one-tap support email, so a locked-out clinician
/// always has a next step. Reused on both the daily challenge
/// (``MfaChallengeView``) and first-time setup (``MfaSetupView``).
struct MfaRecoveryLink: View {
    @State private var showHelp = false

    var body: some View {
        Button {
            AurionHaptics.selection()
            showHelp = true
        } label: {
            Text(L("login.mfa.recovery.cantAccess"))
                .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                .foregroundColor(.aurionGold)
                .underline()
                .frame(maxWidth: .infinity)
                .frame(minHeight: AurionSpacing.hitMin)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(L("login.mfa.recovery.cantAccess"))
        .accessibilityHint(L("login.mfa.recovery.a11yHint"))
        .sheet(isPresented: $showHelp) {
            MfaRecoverySheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }
}

/// Guidance sheet: explains why MFA can't be self-reset and offers a one-tap
/// email to support / the clinic administrator. Matches the navy-gradient
/// glass aesthetic of the MFA screens that present it.
private struct MfaRecoverySheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(spacing: 10) {
                        Image(systemName: "questionmark.circle.fill")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundColor(.aurionGold)
                            .accessibilityHidden(true)
                        Text(L("login.mfa.recovery.title"))
                            .aurionFont(20, weight: .semibold, relativeTo: .title3)
                            .foregroundColor(.white)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.top, 12)

                    Text(L("login.mfa.recovery.body"))
                        .aurionFont(14, relativeTo: .subheadline)
                        .foregroundColor(Color.aurionOnNavySecondary)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    Button {
                        AurionHaptics.impact(.medium)
                        if let url = URL(string: "mailto:\(MfaRecovery.supportEmail)") {
                            openURL(url)
                        }
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "envelope.fill")
                                .font(.system(size: 15, weight: .semibold))
                            Text(L("login.mfa.recovery.emailButton"))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .accessibilityHint(L("login.mfa.recovery.emailA11yHint"))

                    Text(MfaRecovery.supportEmail)
                        .aurionFont(13, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.white.opacity(0.7))
                        .frame(maxWidth: .infinity, alignment: .center)
                        .textSelection(.enabled)
                }
                .padding(24)
            }
            .safeAreaInset(edge: .bottom) {
                Button {
                    AurionHaptics.selection()
                    dismiss()
                } label: {
                    Text(L("common.close"))
                        .aurionFont(15, weight: .semibold, relativeTo: .body)
                        .foregroundColor(.white.opacity(0.85))
                        .frame(maxWidth: .infinity)
                        .frame(minHeight: AurionSpacing.hitMin)
                        .contentShape(Rectangle())
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 12)
            }
        }
    }
}
