import Combine
import SwiftUI

/// In-app password reset screen, presented when the user taps the
/// reset-password link in their email (AUTH-UNIVERSAL-LINKS). The
/// token arrives off the deep-linked URL captured by ``AurionApp``;
/// this view collects the new password + confirm, then calls the
/// existing ``AurionAuth/resetPassword(token:newPassword:)`` endpoint.
///
/// The fallback path — user without the iOS app, or AASA lookup
/// failed — still routes through Safari to the web portal's
/// `/reset-password` page (PR #238); iOS handles that degradation
/// automatically without anything from us.
///
/// Visual treatment matches ``ForgotPasswordView`` so the back-and-
/// forth feels like one continuous gate: navy gradient, glass card,
/// gold halo, cancel via top-left chevron. The success panel mirrors
/// the email-sent confirmation panel.
///
/// Security posture:
///  - The token is held in `let token: String` for the lifetime of
///    the view. Never persisted to Keychain (single-use), never
///    rendered into the UI, never logged.
///  - Validation runs locally (8+ chars, matches confirm) before
///    any network call — keeps the wire surface narrow.
///  - 4xx backend responses surface via ``AuthError/invalidResetToken``
///    → a localized "expired or already used" banner. The user is
///    pointed back to the forgot-password flow, not stuck on the
///    reset screen.
///  - The password-length rule (8+ chars) mirrors the web side's
///    `web/lib/password-validation.ts` and the backend's Pydantic
///    `Field(min_length=8, max_length=128)`. Three implementations,
///    same rule by intent — keep them in lockstep.
struct ResetPasswordView: View {
    /// The single-use reset token, extracted from the email link's
    /// `?token=` query param. Lives only in view state — never
    /// persisted, never echoed in the UI.
    let token: String
    let onDismiss: () -> Void

    /// Injectable for tests — overrides the network call site
    /// without requiring URLProtocol setup. Production calls through
    /// ``AurionAuth/shared``.
    var resetPassword: (String, String) async throws -> Void = { token, newPassword in
        try await AurionAuth.shared.resetPassword(token: token, newPassword: newPassword)
    }

    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var showNew = false
    @State private var showConfirm = false
    @State private var isSubmitting = false
    @State private var didSubmit = false
    @State private var transientError: String?
    @FocusState private var focusedField: Field?

    enum Field { case newPassword, confirm }

    /// Minimum password length — mirrors `web/lib/password-validation.ts`
    /// (`PASSWORD_MIN_LENGTH = 8`) and the backend's Pydantic
    /// `ResetPasswordRequest.new_password` `min_length=8` constraint.
    static let passwordMinLength = 8

    private var passwordsMatch: Bool {
        !confirmPassword.isEmpty && newPassword == confirmPassword
    }

    private var canSubmit: Bool {
        !isSubmitting &&
            newPassword.count >= Self.passwordMinLength &&
            passwordsMatch
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                topBar
                // Scrollable so the two password fields stay reachable with
                // the keyboard up at large Dynamic Type sizes; the min-height
                // frame keeps the card vertically centered when it fits.
                GeometryReader { proxy in
                    ScrollView {
                        VStack(spacing: 0) {
                            Spacer(minLength: 24)
                            card
                                .padding(.horizontal, 24)
                            Spacer(minLength: 24)
                        }
                        .frame(minHeight: proxy.size.height)
                    }
                    .scrollBounceBehavior(.basedOnSize)
                    .scrollDismissesKeyboard(.interactively)
                }
            }
        }
        .onAppear {
            // Only auto-focus on entry; re-focusing after the success
            // panel renders would interrupt VoiceOver.
            if !didSubmit { focusedField = .newPassword }
        }
    }

    // MARK: - Subviews

    private var topBar: some View {
        HStack {
            Button {
                AurionHaptics.selection()
                onDismiss()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.left")
                    Text(L("login.resetPassword.backToLogin"))
                }
                .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.white.opacity(0.8))
            }
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.top, 20)
    }

    @ViewBuilder
    private var card: some View {
        if didSubmit {
            successCard
        } else {
            formCard
        }
    }

    private var formCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(L("login.resetPassword.title"))
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .foregroundColor(.white)
                Text(L("login.resetPassword.subtitle"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(Color.aurionOnNavySecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            passwordField(
                label: L("login.resetPassword.newPasswordLabel"),
                text: $newPassword,
                field: .newPassword,
                isVisible: $showNew,
                submit: .next,
                onSubmit: { focusedField = .confirm }
            )

            passwordField(
                label: L("login.resetPassword.confirmLabel"),
                text: $confirmPassword,
                field: .confirm,
                isVisible: $showConfirm,
                submit: .done,
                onSubmit: {
                    if canSubmit { Task { await submit() } }
                }
            )

            // Inline validation hints — mirror the web side's
            // local-validation strings. Surfaced only when the user
            // has typed something so empty-field state stays quiet.
            if !newPassword.isEmpty,
               newPassword.count < Self.passwordMinLength {
                Text(L("login.resetPassword.invalidLength"))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(Color.aurionOnNavyError)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if !confirmPassword.isEmpty, !passwordsMatch {
                Text(L("login.resetPassword.mismatch"))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(Color.aurionOnNavyError)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            Button {
                AurionHaptics.impact(.medium)
                Task { await submit() }
            } label: {
                HStack(spacing: 10) {
                    if isSubmitting {
                        ProgressView().tint(.aurionNavy)
                        Text(L("login.resetPassword.submitting"))
                    } else {
                        Image(systemName: "lock.rotation")
                            .font(.system(size: 16, weight: .semibold))
                        Text(L("login.resetPassword.submitButton"))
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
        .padding(24)
        .background(Color.white.opacity(0.06))
        .cornerRadius(18)
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.white.opacity(0.10), lineWidth: 1)
        )
    }

    private var successCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 28, weight: .regular))
                    .foregroundColor(.aurionGold)
                Text(L("login.resetPassword.successTitle"))
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .foregroundColor(.white)
            }

            Text(L("login.resetPassword.success"))
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(Color.aurionOnNavySecondary)
                .fixedSize(horizontal: false, vertical: true)

            Button {
                AurionHaptics.selection()
                onDismiss()
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "arrow.right.circle.fill")
                        .font(.system(size: 16, weight: .semibold))
                    Text(L("login.resetPassword.signIn"))
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(AurionPrimaryButtonStyle())
        }
        .padding(24)
        .background(Color.white.opacity(0.06))
        .cornerRadius(18)
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.white.opacity(0.10), lineWidth: 1)
        )
    }

    @ViewBuilder
    private func passwordField(
        label: String,
        text: Binding<String>,
        field: Field,
        isVisible: Binding<Bool>,
        submit: SubmitLabel,
        onSubmit: @escaping () -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                .tracking(0.5)
                .foregroundColor(Color.aurionOnNavyFootnote)
            HStack(spacing: 8) {
                Group {
                    if isVisible.wrappedValue {
                        TextField("", text: text)
                    } else {
                        SecureField("", text: text)
                    }
                }
                .focused($focusedField, equals: field)
                .accessibilityLabel(label)
                .submitLabel(submit)
                .onSubmit(onSubmit)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textContentType(.newPassword)
                .foregroundColor(.white)
                .tint(.aurionGold)

                Button {
                    AurionHaptics.selection()
                    isVisible.wrappedValue.toggle()
                } label: {
                    Image(systemName: isVisible.wrappedValue ? "eye.slash" : "eye")
                        .foregroundColor(Color.aurionOnNavyFootnote)
                }
                .accessibilityLabel(
                    isVisible.wrappedValue
                        ? L("login.resetPassword.hidePassword")
                        : L("login.resetPassword.showPassword")
                )
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 11)
            .background(Color.white.opacity(0.08))
            .cornerRadius(10)
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(
                        Color.white.opacity(focusedField == field ? 0.35 : 0.10),
                        lineWidth: 1
                    )
            )
        }
    }

    // MARK: - Logic

    @MainActor
    func submit() async {
        guard canSubmit else { return }
        isSubmitting = true
        transientError = nil
        do {
            try await resetPassword(token, newPassword)
            isSubmitting = false
            didSubmit = true
            AurionHaptics.notification(.success)
        } catch let error as AuthError where error == .invalidResetToken {
            // Token is single-use and short-lived; if it's already
            // consumed or expired, point the user back to forgot-
            // password rather than stranding them on this screen.
            isSubmitting = false
            transientError = L("login.resetPassword.tokenInvalid")
            AurionHaptics.notification(.error)
        } catch {
            // Network or malformed — show the localized description
            // and let the user retry. The form stays open.
            isSubmitting = false
            transientError = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }
}

/// Cross-cutting bus for an inbound Universal Link reset token. Lives
/// at the App scope; ``AurionApp`` writes when a link is consumed and
/// ``ContentView`` reads to drive the reset full-screen cover.
///
/// Kept minimal — exactly one `@Published` field. Adding multi-link
/// types here later (e.g. magic-link sign-in) should re-think the
/// shape rather than balloon this single field.
///
/// Same `@MainActor final class ... ObservableObject` shape as
/// ``AppLockManager``, ``TourCoordinator``, ``AppState`` — keeps the
/// `objectWillChange` synthesis isolated to the main actor so
/// `@StateObject` / `@EnvironmentObject` callers don't see a
/// concurrency mismatch under Swift 6 strict isolation.
@MainActor
final class ResetLinkPayload: ObservableObject {
    @Published var token: String?

    /// Shared sink the cold-launch ``AppDelegate`` writes into.
    /// `AurionApp` overwrites this on `init` so the delegate can
    /// hand off the activity that fired before the SwiftUI view
    /// hierarchy was alive. Defaults to a throwaway instance so any
    /// pre-app code paths don't crash on nil unwrap.
    static var shared: ResetLinkPayload = ResetLinkPayload()

    init() {}
}

/// AUTH-UNIVERSAL-LINKS — extract a non-empty `?token=` from an
/// inbound reset-password Universal Link, or return nil if the URL
/// doesn't claim the reset surface. Tolerates the optional trailing
/// slash that Next.js' `trailingSlash: true` config sometimes leaves
/// on URLs before iOS' swcd normalisation (`/reset-password/?token=…`
/// — same path semantics, just a different surface form).
///
/// Pulled out of ``AurionApp.body`` so both the warm-path
/// ``.onContinueUserActivity`` handler AND the cold-launch
/// ``AurionAppDelegate.application(_:continue:restorationHandler:)``
/// can share the exact same validation rule. Otherwise the two paths
/// would silently drift — and the cold path is the one that fires
/// when the user taps a reset link from a fresh app launch (every
/// pilot user's first encounter with this flow).
@MainActor
enum ResetLinkExtractor {
    static func token(from url: URL) -> String? {
        guard url.host == "portal.aurionclinical.com" else { return nil }
        // Tolerate the trailing-slash variant — see docstring.
        let path = url.path
        guard path == "/reset-password" || path == "/reset-password/" else { return nil }
        guard
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
            let token = components.queryItems?
                .first(where: { $0.name == "token" })?
                .value,
            !token.isEmpty
        else { return nil }
        return token
    }
}
