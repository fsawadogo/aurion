import SwiftUI

/// Identifiable wrapper so the MFA challenge screen can be presented via
/// `.fullScreenCover(item:)`, matching the new-password pattern that
/// used to live in the login state machine.
///
/// `challengeToken` is the short-lived JWT the backend returns from
/// `/auth/login` when the account has MFA enrolled; submitting it back
/// to `/auth/mfa/verify-login` with a valid TOTP code finalises the
/// login. The token has a 5-minute TTL — long enough for any human
/// to pull a code out of their authenticator app, short enough that a
/// stolen device can't replay it.
struct MfaChallenge: Identifiable {
    let id = UUID()
    let challengeToken: String
    let userEmail: String
}

/// Daily TOTP challenge — the user already enrolled, backend `/auth/login`
/// returned `mfa_required: true` + a challenge token, and now we collect
/// the 6-digit code from the authenticator app and ship it back through
/// `verifyLoginMfa`.
///
/// Visual treatment mirrors the deleted `NewPasswordView` so the
/// post-password chain feels like one continuous gate: navy gradient,
/// glass card, dismiss via top-left cancel.
struct MfaChallengeView: View {
    let challenge: MfaChallenge
    let onSuccess: (AuthSession) -> Void
    let onCancel: () -> Void

    @State private var code: String = ""
    @State private var isSubmitting = false
    @State private var error: String?

    private var canSubmit: Bool {
        TotpCodeField.isComplete(code) && !isSubmitting
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                HStack {
                    Button {
                        // Cancel returns to the login screen without
                        // touching the saved biometric credential — the
                        // user only typed a password, no auth state
                        // changed on the Keychain side.
                        AurionHaptics.selection()
                        onCancel()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "chevron.left")
                            Text(L("login.mfa.challenge.cancelButton"))
                        }
                        .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.white.opacity(0.8))
                    }
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.top, 20)

                Spacer()

                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(L("login.mfa.challenge.title"))
                            .aurionFont(22, weight: .semibold, relativeTo: .title2)
                            .foregroundColor(.white)
                        Text(L("login.mfa.challenge.subtitle"))
                            .aurionFont(13, relativeTo: .footnote)
                            .foregroundColor(Color.aurionOnNavySecondary)
                    }

                    TotpCodeField(code: $code, onComplete: {
                        if canSubmit { Task { await submit() } }
                    })
                    .frame(maxWidth: .infinity)

                    Button {
                        AurionHaptics.impact(.medium)
                        Task { await submit() }
                    } label: {
                        HStack(spacing: 10) {
                            if isSubmitting {
                                ProgressView().tint(.aurionNavy)
                                Text(L("login.mfa.challenge.verifyButton"))
                            } else {
                                Image(systemName: "checkmark.shield.fill")
                                    .font(.system(size: 16, weight: .semibold))
                                Text(L("login.mfa.challenge.verifyButton"))
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .disabled(!canSubmit)

                    if let error {
                        Text(error)
                            .aurionFont(12, relativeTo: .caption)
                            .foregroundColor(Color.aurionOnNavyError)
                            .multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(24)
                .background(Color.white.opacity(0.06))
                .cornerRadius(18)
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .stroke(Color.white.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 24)

                Spacer()
            }
        }
    }

    @MainActor
    private func submit() async {
        isSubmitting = true
        error = nil
        do {
            let session = try await AurionAuth.shared.verifyLoginMfa(
                challengeToken: challenge.challengeToken,
                code: code
            )
            AurionHaptics.notification(.success)
            onSuccess(session)
        } catch AuthError.invalidCredentials, AuthError.mfaCodeMismatch {
            // Backend collapses every bad-code path to the same 401.
            // Show a generic, code-free message and clear the field
            // so the user can re-enter without echoing the bad input.
            isSubmitting = false
            error = L("login.mfa.challenge.invalidCode")
            code = ""
            AurionHaptics.notification(.error)
        } catch {
            isSubmitting = false
            self.error = error.localizedDescription
            code = ""
            AurionHaptics.notification(.error)
        }
    }
}
