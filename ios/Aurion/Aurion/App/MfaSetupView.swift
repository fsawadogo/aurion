import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI
import UIKit

/// Identifiable wrapper for `.fullScreenCover(item:)`.
struct MfaSetupChallenge: Identifiable {
    let id = UUID()
    let session: String
    let username: String
}

/// First-time TOTP enrolment.
///
/// Two phases driven by `phase`:
///   1. ``Phase/display`` — fetches the shared secret from Cognito,
///      renders a QR (`otpauth://totp/...`) and the raw base32 string,
///      offers a copy button.
///   2. ``Phase/confirm`` — collects the 6-digit code from the
///      authenticator app and calls `verifyTotpSetup` → `signInForMfaSetup`
///      → `.authenticated`.
///
/// The shared secret lives in `@State` only; it leaves memory the moment
/// this view is dismissed. Cognito holds the canonical association —
/// we never persist it to Keychain or anywhere else.
struct MfaSetupView: View {
    let challenge: MfaSetupChallenge
    let onSuccess: (CognitoNativeAuth.SignInOutcome) -> Void
    let onCancel: () -> Void

    enum Phase {
        case loading
        case display
        case confirm
        case finishing
    }

    @State private var phase: Phase = .loading
    /// Cognito-returned base32 secret. In-memory only — never logged,
    /// never written to Keychain. Cleared on view dismiss.
    @State private var secret: String = ""
    /// Session token returned by `AssociateSoftwareToken` when the
    /// associate call was Session-based (the MFA_SETUP flow). Needed by
    /// `verifyTotpSetup`.
    @State private var setupSession: String? = nil
    @State private var code: String = ""
    @State private var error: String?
    @State private var copied: Bool = false

    private static let issuer = "Aurion"

    private var qrPayload: String {
        // otpauth URI per RFC 6238 §C — what every authenticator-app QR
        // reader expects. Username is the Cognito username (email).
        let label = "\(Self.issuer):\(challenge.username)"
            .addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? ""
        return "otpauth://totp/\(label)?secret=\(secret)&issuer=\(Self.issuer)"
    }

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

    private var loadingCard: some View {
        VStack(spacing: 14) {
            ProgressView().tint(.aurionGold)
            Text(L("login.mfa.setup.title"))
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.white)
            if let error {
                Text(error)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(Color.aurionOnNavyError)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
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

            if let qrImage = qrImage(from: qrPayload) {
                Image(uiImage: qrImage)
                    .interpolation(.none)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 200, height: 200)
                    .padding(10)
                    .background(Color.white)
                    .cornerRadius(12)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .accessibilityLabel(L("login.mfa.setup.title"))
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
                    Button {
                        AurionHaptics.selection()
                        UIPasteboard.general.string = secret
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
            })
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

    /// Cognito-issued base32 is a single run — chunk into groups of 4 so
    /// the manual-entry case (no QR scanner handy) is readable.
    private var formattedSecret: String {
        guard !secret.isEmpty else { return "" }
        return stride(from: 0, to: secret.count, by: 4).map { offset -> String in
            let start = secret.index(secret.startIndex, offsetBy: offset)
            let end = secret.index(start, offsetBy: min(4, secret.count - offset))
            return String(secret[start..<end])
        }.joined(separator: " ")
    }

    @MainActor
    private func loadSecret() async {
        guard secret.isEmpty else { return }
        do {
            // First, advance the MFA_SETUP challenge to get a fresh
            // Session for AssociateSoftwareToken. Without this hop,
            // AssociateSoftwareToken would reject the InitiateAuth
            // Session as having "wrong purpose".
            let setupOutcome = try await CognitoNativeAuth.shared.signInForMfaSetup(
                session: challenge.session,
                username: challenge.username
            )
            let sessionForAssociate: String
            switch setupOutcome {
            case .mfaSetupRequired(let newSession, _):
                sessionForAssociate = newSession
            case .authenticated(let auth):
                // Unusual but documented — if the pool let us through
                // without enrolment, just authenticate.
                onSuccess(.authenticated(auth))
                return
            default:
                error = NativeAuthError.malformed.errorDescription
                return
            }

            let setup = try await CognitoNativeAuth.shared.beginTotpSetup(
                accessToken: nil,
                session: sessionForAssociate
            )
            secret = setup.secretCode
            setupSession = setup.session ?? sessionForAssociate
            withAnimation(AurionAnimation.smooth) {
                phase = .display
            }
        } catch {
            self.error = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }

    @MainActor
    private func confirm() async {
        guard canConfirm else { return }
        phase = .finishing
        error = nil
        do {
            let device = UIDevice.current.name.isEmpty
                ? "Aurion iPhone"
                : UIDevice.current.name
            let verify = try await CognitoNativeAuth.shared.verifyTotpSetup(
                accessToken: nil,
                session: setupSession,
                code: code,
                friendlyDeviceName: device
            )
            switch verify {
            case .codeMismatch:
                phase = .confirm
                code = ""
                error = L("login.mfa.setup.codeMismatch")
                AurionHaptics.notification(.error)
            case .success(let nextSession):
                // Verify SUCCESS — now finish the MFA_SETUP challenge so
                // Cognito returns AuthenticationResult and we land in
                // `.authenticated`. The session to use is whatever
                // VerifySoftwareToken returned (preferred), falling back
                // to the associate session.
                let session = nextSession ?? setupSession ?? challenge.session
                let outcome = try await CognitoNativeAuth.shared.signInForMfaSetup(
                    session: session,
                    username: challenge.username
                )
                AurionHaptics.notification(.success)
                onSuccess(outcome)
            }
        } catch {
            phase = .confirm
            code = ""
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
