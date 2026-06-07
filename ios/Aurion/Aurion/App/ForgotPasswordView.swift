import SwiftUI

/// Email-link password reset entry screen.
///
/// Single email field + "Send reset link" CTA. The backend ALWAYS
/// returns 204 from `/auth/forgot-password` whether or not the email
/// matches an active account, and this view shows the SAME confirmation
/// panel for every input so the response can't be used to enumerate
/// account existence.
///
/// The reset link itself opens the web portal's reset page (see the
/// web rebase PR) — we deliberately do NOT implement a
/// `aurion://reset?token=...` deep link in iOS for the pilot. That
/// would add a substantial parsing + validation surface and the web
/// flow already covers the path.
///
/// Visual treatment matches `LoginView` so the back-and-forth feels
/// like one continuous gate: navy gradient, glass card, cancel via
/// top-left chevron.
struct ForgotPasswordView: View {
    let onDismiss: () -> Void

    /// Injectable for tests — overrides the network call site without
    /// requiring URLProtocol setup in the view test suite. Production
    /// always calls through ``AurionAuth.shared``.
    var requestReset: (String) async throws -> Void = { email in
        try await AurionAuth.shared.requestPasswordReset(email: email)
    }

    @State private var email = ""
    @State private var isSubmitting = false
    @State private var didSubmit = false
    @State private var transientError: String?
    @FocusState private var emailFocused: Bool

    private var canSubmit: Bool {
        !isSubmitting && email.trimmingCharacters(in: .whitespaces).contains("@")
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                topBar
                Spacer(minLength: 24)
                card
                    .padding(.horizontal, 24)
                Spacer()
            }
        }
        .onAppear {
            // Only auto-focus on entry — re-focusing after the
            // confirmation panel renders would interrupt VoiceOver.
            if !didSubmit { emailFocused = true }
        }
    }

    // MARK: - Subviews

    private var topBar: some View {
        AuthBackBar(
            label: L("login.forgotPassword.backToLogin"),
            onDismiss: onDismiss
        )
    }

    @ViewBuilder
    private var card: some View {
        if didSubmit {
            confirmationCard
        } else {
            formCard
        }
    }

    private var formCard: some View {
        AuthGlassCard {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(L("login.forgotPassword.title"))
                        .aurionFont(22, weight: .semibold, relativeTo: .title2)
                        .foregroundColor(.white)
                    Text(L("login.forgotPassword.subtitle"))
                        .aurionFont(13, relativeTo: .footnote)
                        .foregroundColor(Color.aurionOnNavySecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text(L("login.forgotPassword.emailLabel"))
                        .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                        .tracking(0.5)
                        .foregroundColor(Color.aurionOnNavyFootnote)
                    TextField("", text: $email)
                        .focused($emailFocused)
                        .submitLabel(.send)
                        .onSubmit {
                            if canSubmit { Task { await submit() } }
                        }
                        .accessibilityLabel(L("login.forgotPassword.emailLabel"))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.emailAddress)
                        .textContentType(.username)
                        .foregroundColor(.white)
                        .tint(.aurionGold)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 11)
                        .background(Color.white.opacity(0.08))
                        .cornerRadius(10)
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(
                                    Color.white.opacity(emailFocused ? 0.35 : 0.10),
                                    lineWidth: 1
                                )
                        )
                }

                Button {
                    AurionHaptics.impact(.medium)
                    Task { await submit() }
                } label: {
                    HStack(spacing: 10) {
                        if isSubmitting {
                            ProgressView().tint(.aurionNavy)
                            Text(L("login.forgotPassword.sending"))
                        } else {
                            Image(systemName: "paperplane.fill")
                                .font(.system(size: 16, weight: .semibold))
                            Text(L("login.forgotPassword.sendButton"))
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(AurionPrimaryButtonStyle())
                .disabled(!canSubmit)

                if let transientError {
                    Text(transientError)
                        .aurionFont(12, relativeTo: .caption)
                        .foregroundColor(Color.aurionOnNavyError)
                        .multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private var confirmationCard: some View {
        AuthGlassCard {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 12) {
                    Image(systemName: "envelope.badge.fill")
                        .font(.system(size: 28, weight: .regular))
                        .foregroundColor(.aurionGold)
                    Text(L("login.forgotPassword.title"))
                        .aurionFont(22, weight: .semibold, relativeTo: .title2)
                        .foregroundColor(.white)
                }

                Text(L("login.forgotPassword.confirmation"))
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(Color.aurionOnNavySecondary)
                    .fixedSize(horizontal: false, vertical: true)

                Button {
                    AurionHaptics.selection()
                    onDismiss()
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "arrow.left.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                        Text(L("login.forgotPassword.backToLogin"))
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(AurionPrimaryButtonStyle())
            }
        }
    }

    // MARK: - Logic

    @MainActor
    private func submit() async {
        guard canSubmit else { return }
        isSubmitting = true
        transientError = nil
        let trimmed = email.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        do {
            try await requestReset(trimmed)
            // Whether or not the email was on file, the backend
            // returned 204 — flip to the confirmation panel either
            // way. This is the account-enumeration-safe contract:
            // observable response shape is identical for every email.
            isSubmitting = false
            didSubmit = true
            AurionHaptics.notification(.success)
        } catch {
            // Real transport failures (offline, 5xx) surface as a soft
            // recoverable banner — the form stays open so the user can
            // retry. We deliberately do NOT auto-flip to the
            // confirmation panel on error: that would hide the failure
            // from the user and they'd never get a reset link.
            isSubmitting = false
            transientError = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }
}
