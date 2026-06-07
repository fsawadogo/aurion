import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI
import UIKit

/// First-time TOTP enrolment view.
///
/// Two phases driven by `phase`:
///   1. ``Phase/display`` — fetches the shared secret + provisioning URI
///      from the backend via `AurionAuth.beginMfaSetup`, renders a QR
///      code (`otpauth://totp/...`) and the raw base32 string, offers a
///      copy button.
///   2. ``Phase/confirm`` — collects the 6-digit code from the
///      authenticator app and calls `AurionAuth.verifyMfaSetup`.
///
/// The shared secret lives in `@State` only; it leaves memory the
/// moment this view is dismissed. The backend holds the canonical
/// KMS-encrypted copy — we never persist it to Keychain or anywhere
/// else.
///
/// Compared to the Cognito-era ancestor this view replaces, the
/// backend protocol is structurally simpler — two calls instead of
/// four — because the backend persists the in-progress secret
/// server-side, so the QR phase and the verify phase need no
/// session-token continuity.
struct MfaSetupView: View {
    let onSuccess: () -> Void
    let onCancel: () -> Void

    enum Phase {
        case loading
        case display
        case confirm
        case finishing
    }

    @State private var phase: Phase = .loading
    /// Backend-returned base32 secret. In-memory only — never logged,
    /// never written to Keychain. Cleared on view dismiss.
    @State private var secret: String = ""
    /// Pre-built `otpauth://...` URI the backend hands back along with
    /// the secret. Used directly as the QR payload so iOS doesn't
    /// re-encode it (any drift from the backend's encoding could break
    /// authenticator-app parsing).
    @State private var provisioningURI: String = ""
    @State private var code: String = ""
    @State private var error: String?
    @State private var copied: Bool = false
    /// Bumped after a bad code clears the field, so ``TotpCodeField`` can
    /// re-assert keyboard focus without the user tapping a cell again.
    @State private var focusResetToken = 0

    private var canConfirm: Bool {
        TotpCodeField.isComplete(code) && phase == .confirm
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                topBar
                Spacer(minLength: 12)
                cardContent
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
        .task {
            await loadSecret()
        }
    }

    // MARK: - Subviews

    private var topBar: some View {
        HStack {
            Button {
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
    }

    @ViewBuilder
    private var cardContent: some View {
        switch phase {
        case .loading:
            loadingCard
        case .display:
            displayCard
        case .confirm, .finishing:
            confirmCard
        }
    }

    @ViewBuilder
    private var loadingCard: some View {
        if let error {
            // beginMfaSetup() failed — surface the error with a retry path
            // instead of leaving the spinner running forever.
            VStack(spacing: 14) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 26))
                    .foregroundColor(Color.aurionOnNavyError)
                Text(L("login.mfa.setup.title"))
                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                    .foregroundColor(.white)
                Text(error)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(Color.aurionOnNavyError)
                    .multilineTextAlignment(.center)

                Button {
                    AurionHaptics.impact(.medium)
                    Task { await retryLoadSecret() }
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 15, weight: .semibold))
                        Text(L("common.retry"))
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(AurionPrimaryButtonStyle())

                Button {
                    AurionHaptics.selection()
                    onCancel()
                } label: {
                    Text(L("common.cancel"))
                        .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                        .foregroundColor(.white.opacity(0.8))
                }
                .padding(.top, 2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
        } else {
            VStack(spacing: 14) {
                ProgressView().tint(.aurionGold)
                Text(L("login.mfa.setup.title"))
                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                    .foregroundColor(.white)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
        }
    }

    private var displayCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(L("login.mfa.setup.title"))
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .foregroundColor(.white)
                Text(L("login.mfa.setup.intro"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(Color.aurionOnNavySecondary)
            }

            if let qrImage = qrImage(from: provisioningURI) {
                Image(uiImage: qrImage)
                    .interpolation(.none)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 200, height: 200)
                    .padding(10)
                    .background(Color.white)
                    .cornerRadius(12)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .accessibilityLabel(L("login.mfa.setup.qrA11y"))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(L("login.mfa.setup.secretLabel"))
                    .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                    .tracking(0.5)
                    .foregroundColor(Color.aurionOnNavyFootnote)
                HStack(spacing: 10) {
                    Text(formattedSecret)
                        .aurionFont(13, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        // Spell the base32 out so VoiceOver reads it one
                        // character at a time for manual authenticator entry,
                        // instead of one run-on token.
                        .accessibilityLabel(spelledOutSecret)
                    Button {
                        AurionHaptics.selection()
                        UIPasteboard.general.string = secret
                        // VoiceOver gets no visual cue from the inline label
                        // swap, so announce the copy explicitly.
                        UIAccessibility.post(
                            notification: .announcement,
                            argument: L("login.mfa.setup.copied")
                        )
                        withAnimation(AurionAnimation.smooth) { copied = true }
                        Task {
                            try? await Task.sleep(nanoseconds: 1_500_000_000)
                            withAnimation(AurionAnimation.smooth) { copied = false }
                        }
                    } label: {
                        Text(copied
                            ? L("login.mfa.setup.copied")
                            : L("login.mfa.setup.copySecret"))
                            .aurionFont(12, weight: .semibold, relativeTo: .caption)
                            .foregroundColor(.aurionNavy)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Color.aurionGold)
                            .cornerRadius(8)
                            .frame(minHeight: AurionSpacing.hitMin)
                            .contentShape(Rectangle())
                    }
                }
                .padding(12)
                .background(Color.white.opacity(0.08))
                .cornerRadius(10)
            }

            Button {
                AurionHaptics.impact(.medium)
                code = ""
                error = nil
                withAnimation(AurionAnimation.smooth) {
                    phase = .confirm
                }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "arrow.right.circle.fill")
                        .font(.system(size: 16, weight: .semibold))
                    Text(L("login.mfa.setup.completeButton"))
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(AurionPrimaryButtonStyle())
        }
    }

    private var confirmCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(L("login.mfa.setup.title"))
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .foregroundColor(.white)
                Text(L("login.mfa.setup.confirmLabel"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(Color.aurionOnNavySecondary)
            }

            TotpCodeField(code: $code, onComplete: {
                if canConfirm { Task { await confirm() } }
            }, resetToken: focusResetToken)
            .frame(maxWidth: .infinity)

            Button {
                AurionHaptics.impact(.medium)
                Task { await confirm() }
            } label: {
                HStack(spacing: 10) {
                    if phase == .finishing {
                        ProgressView().tint(.aurionNavy)
                        Text(L("login.mfa.setup.completeButton"))
                    } else {
                        Image(systemName: "checkmark.shield.fill")
                            .font(.system(size: 16, weight: .semibold))
                        Text(L("login.mfa.setup.completeButton"))
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(AurionPrimaryButtonStyle())
            .disabled(!canConfirm)

            if let error {
                Text(error)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(Color.aurionOnNavyError)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    // MARK: - Logic

    /// Base32 secret in 4-char groups so the manual-entry case (no QR
    /// scanner handy) is readable.
    private var formattedSecret: String {
        guard !secret.isEmpty else { return "" }
        return stride(from: 0, to: secret.count, by: 4).map { offset -> String in
            let start = secret.index(secret.startIndex, offsetBy: offset)
            let end = secret.index(start, offsetBy: min(4, secret.count - offset))
            return String(secret[start..<end])
        }.joined(separator: " ")
    }

    /// The secret with each character separated so VoiceOver dictates it
    /// letter-by-letter — the only practical way to enter a base32 key by
    /// hand under VoiceOver, since the QR code itself is unreadable to it.
    private var spelledOutSecret: String {
        secret.map(String.init).joined(separator: " ")
    }

    @MainActor
    private func loadSecret() async {
        guard secret.isEmpty else { return }
        do {
            let setup = try await AurionAuth.shared.beginMfaSetup()
            secret = setup.secret
            provisioningURI = setup.provisioningURI
            withAnimation(AurionAnimation.smooth) {
                phase = .display
            }
        } catch {
            self.error = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }

    /// Re-arm the loading state and re-run ``loadSecret()`` after a failed
    /// fetch. Clearing `error` first swaps the retry card back to the
    /// spinner while the request is in flight.
    @MainActor
    private func retryLoadSecret() async {
        error = nil
        await loadSecret()
    }

    @MainActor
    private func confirm() async {
        guard canConfirm else { return }
        phase = .finishing
        error = nil
        do {
            let outcome = try await AurionAuth.shared.verifyMfaSetup(code: code)
            switch outcome {
            case .codeMismatch:
                phase = .confirm
                code = ""
                focusResetToken += 1
                error = L("login.mfa.setup.codeMismatch")
                AurionHaptics.notification(.error)
            case .success:
                AurionHaptics.notification(.success)
                onSuccess()
            }
        } catch {
            phase = .confirm
            code = ""
            focusResetToken += 1
            self.error = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }

    // MARK: - QR generation

    /// Render the otpauth URI as a high-contrast QR code. Uses the
    /// CoreImage built-in generator — no third-party QR dependency.
    private func qrImage(from string: String) -> UIImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        // Scale up so the iOS image renderer doesn't soft-blur the cells.
        let scale: CGFloat = 8
        let transformed = output.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let context = CIContext()
        guard let cg = context.createCGImage(transformed, from: transformed.extent) else {
            return nil
        }
        return UIImage(cgImage: cg)
    }
}
