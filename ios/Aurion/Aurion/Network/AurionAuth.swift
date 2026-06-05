import Foundation

/// The SOLE iOS auth client. Replaces ``CognitoAuth`` and
/// ``CognitoNativeAuth`` after AUTH-PIVOT-BACKEND (PR #234) shipped the
/// backend-issued JWT + TOTP + email-link reset endpoints.
///
/// Every call is a plain JSON POST/GET against
/// `\(AppConfig.apiBaseURL)/api/v1/auth/...`. Token storage continues to
/// route through ``KeychainHelper`` — the storage contract did NOT change
/// (`saveTokens(accessToken:, idToken:, refreshToken:, expiresAt:)`); we
/// pass the backend-issued access token into both the access and id slots
/// so ``bearerToken()``'s lookup path keeps working without a Keychain
/// migration. Users re-sign-in once during the cutover window anyway.
///
/// Cutover compatibility: the backend's `AUTH_ACCEPT_LEGACY_COGNITO_JWT=true`
/// flag means the dev backend will continue to accept Cognito tokens
/// already in the Keychain. Once a physician signs in through this
/// client, their Keychain is replaced with backend tokens and they
/// proceed on the new path automatically.
@MainActor
final class AurionAuth {
    static let shared = AurionAuth()

    /// Injectable session for tests; production uses the shared session.
    private let session: URLSession

    init(urlSession: URLSession = .shared) {
        self.session = urlSession
    }

    // MARK: - Outcomes

    /// Result of a `/auth/login` call. Either tokens (signed in) or an
    /// MFA challenge the caller must finish via ``verifyLoginMfa``.
    ///
    /// Note: the backend has no first-sign-in `NEW_PASSWORD_REQUIRED`
    /// ceremony (unlike Cognito) — admin-issued temp passwords behave
    /// like any other password. A forced-rotate-on-first-login UI would
    /// be a separate follow-up; not in scope for the auth pivot.
    enum SignInOutcome {
        case authenticated(AuthSession)
        case mfaRequired(challengeToken: String, userEmail: String)
    }

    /// Result of `/auth/mfa/setup/verify`. Success → enrollment complete,
    /// the next login through this user will be MFA-gated. Code mismatch
    /// → re-enter without losing the secret displayed on the QR screen.
    enum MfaSetupOutcome {
        case success
        case codeMismatch
    }

    // MARK: - /auth/login

    /// Email + password → tokens or MFA challenge.
    ///
    /// On `.authenticated`, the token bundle is persisted to
    /// ``KeychainHelper`` so every downstream ``APIClient.addAuth`` keeps
    /// working unchanged. On `.mfaRequired`, the caller must hand the
    /// `challengeToken` to ``verifyLoginMfa`` after the user enters
    /// their authenticator code.
    func signIn(email: String, password: String) async throws -> SignInOutcome {
        let json = try await postJSON(
            path: "/auth/login",
            body: ["email": email, "password": password]
        )

        if let mfaRequired = json["mfa_required"] as? Bool, mfaRequired,
           let challengeToken = json["mfa_challenge_token"] as? String,
           let userEmail = json["user_email"] as? String {
            return .mfaRequired(challengeToken: challengeToken, userEmail: userEmail)
        }

        let authSession = try parseSession(json)
        persistTokens(authSession)
        return .authenticated(authSession)
    }

    // MARK: - /auth/mfa/verify-login

    /// Finalize an MFA-gated login. The challenge token proves the
    /// caller already cleared the password gate; this submits the TOTP
    /// code from the authenticator app. Bad code → ``AuthError.mfaCodeMismatch``.
    func verifyLoginMfa(challengeToken: String, code: String) async throws -> AuthSession {
        let json = try await postJSON(
            path: "/auth/mfa/verify-login",
            body: ["mfa_challenge_token": challengeToken, "code": code]
        )
        let authSession = try parseSession(json)
        persistTokens(authSession)
        return authSession
    }

    // MARK: - /auth/refresh

    /// Exchange a refresh token for a fresh access + rotated refresh.
    ///
    /// The backend rotates the refresh token in the same transaction —
    /// the old one becomes invalid the moment this call returns. We
    /// persist whatever shape the backend hands back; the response is
    /// the canonical source of truth even if the old token wasn't
    /// echoed explicitly.
    func refresh(refreshToken: String) async throws -> AuthSession {
        let json = try await postJSON(
            path: "/auth/refresh",
            body: ["refresh_token": refreshToken]
        )
        let authSession = try parseSession(json)
        persistTokens(authSession)
        return authSession
    }

    /// Drop-in replacement for the legacy `CognitoAuth.refreshIfNeeded`.
    /// Returns the new ``AuthSession`` when a stored refresh exists, or
    /// nil when there's nothing to refresh. Clears the Keychain on a 401
    /// so ContentView can route back to ``LoginView``.
    func refreshIfNeeded() async throws -> AuthSession? {
        guard let refreshToken = KeychainHelper.shared.getRefreshToken() else {
            return nil
        }
        do {
            return try await refresh(refreshToken: refreshToken)
        } catch AuthError.invalidCredentials, AuthError.network {
            // Treat any auth failure here as "session is gone" — clear
            // local state so the user lands on LoginView, not in a
            // perpetual retry loop with a stale token.
            KeychainHelper.shared.clearTokens()
            throw AuthError.invalidCredentials
        }
    }

    // MARK: - /auth/logout

    /// Revoke a refresh token on the backend. Fire-and-forget — we
    /// always clear local Keychain regardless of the network result,
    /// so a sign-out can't strand the app in a half-signed-in state.
    func logout(refreshToken: String) async {
        _ = try? await postJSON(
            path: "/auth/logout",
            body: ["refresh_token": refreshToken],
            expectingEmptyResponse: true
        )
        KeychainHelper.shared.clearTokens()
    }

    /// Local sign-out — drop the cached tokens with no backend round
    /// trip. Use when ``logout(refreshToken:)`` would be redundant
    /// (already-expired token, no network expected to land).
    func signOut() {
        KeychainHelper.shared.clearTokens()
    }

    // MARK: - /auth/forgot-password + /auth/reset-password

    /// Request an email-link password reset. Backend always returns 204
    /// — no observable account-existence signal — and we treat any
    /// 2xx as success. Errors that DO leak (transport failure, 5xx) get
    /// surfaced as ``AuthError.network`` so the UI can show a soft
    /// "couldn't reach the server" banner without confirming that the
    /// email was on file.
    func requestPasswordReset(email: String) async throws {
        _ = try await postJSON(
            path: "/auth/forgot-password",
            body: ["email": email],
            expectingEmptyResponse: true
        )
    }

    /// Consume a reset token + set the new password. The reset link
    /// arrives via email; the user opens it on the web portal (see the
    /// web rebase PR). We do NOT implement a deep-link reset flow on
    /// iOS — out of scope for the pilot.
    ///
    /// Surfaced for completeness — currently unused by the iOS app
    /// itself, but a tiny in-app reset surface could land later by
    /// calling this with a pasted token.
    func resetPassword(token: String, newPassword: String) async throws {
        do {
            _ = try await postJSON(
                path: "/auth/reset-password",
                body: ["token": token, "new_password": newPassword],
                expectingEmptyResponse: true
            )
        } catch AuthError.invalidCredentials {
            // Backend returns 400 for expired/consumed/unknown tokens;
            // our generic 4xx mapping lands as .invalidCredentials, but
            // the UI should phrase it as a token problem.
            throw AuthError.invalidResetToken
        }
    }

    // MARK: - /auth/mfa/setup + /auth/mfa/setup/verify

    /// Begin TOTP enrollment. Returns the base32 secret + provisioning
    /// URI the QR code is built from.
    ///
    /// The secret travels with the user only — it is displayed and
    /// QR-rendered in `MfaSetupView`, never persisted to Keychain, never
    /// logged. The backend stores its own KMS-encrypted copy and uses
    /// that as the source of truth for `verifyMfaSetup`.
    func beginMfaSetup() async throws -> (secret: String, provisioningURI: String) {
        let json = try await getJSON(path: "/auth/mfa/setup", auth: true)
        guard
            let secret = json["secret"] as? String,
            let provisioningURI = json["provisioning_uri"] as? String
        else {
            throw AuthError.malformed
        }
        return (secret, provisioningURI)
    }

    /// Confirm enrollment by submitting a code from the authenticator
    /// app. The backend persists `mfa_enrolled_at` on success; on
    /// failure we surface `.codeMismatch` so the UI can stay on the
    /// confirm screen without dropping the secret.
    func verifyMfaSetup(code: String) async throws -> MfaSetupOutcome {
        do {
            _ = try await postJSON(
                path: "/auth/mfa/setup/verify",
                body: ["code": code],
                expectingEmptyResponse: true,
                auth: true
            )
            return .success
        } catch AuthError.invalidCredentials {
            // Backend returns 400 with "Invalid code. Try again." — our
            // 4xx mapping lands here; surface as codeMismatch.
            return .codeMismatch
        }
    }

    // MARK: - Internals

    private func parseSession(_ json: [String: Any]) throws -> AuthSession {
        guard
            let accessToken = json["access_token"] as? String,
            let refreshToken = json["refresh_token"] as? String,
            let expiresIn = json["expires_in"] as? Int
        else {
            throw AuthError.malformed
        }
        return AuthSession(
            accessToken: accessToken,
            // Backend issues a single JWT — there's no separate id token.
            // We populate both slots with the access token so the
            // KeychainHelper.bearerToken() fallback chain
            // (getIDToken() ?? loadAuthToken()) keeps returning the
            // correct value without a storage migration.
            idToken: accessToken,
            refreshToken: refreshToken,
            expiresAt: Date().addingTimeInterval(TimeInterval(expiresIn))
        )
    }

    private func persistTokens(_ session: AuthSession) {
        KeychainHelper.shared.saveTokens(
            accessToken: session.accessToken,
            idToken: session.idToken,
            refreshToken: session.refreshToken,
            expiresAt: session.expiresAt
        )
    }

    @discardableResult
    private func postJSON(
        path: String,
        body: [String: Any],
        expectingEmptyResponse: Bool = false,
        auth: Bool = false
    ) async throws -> [String: Any] {
        guard let url = URL(string: "\(AppConfig.apiBaseURL)/api/\(AppConfig.apiVersion)\(path)") else {
            throw AuthError.network
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let token = KeychainHelper.shared.bearerToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request: request, expectingEmptyResponse: expectingEmptyResponse)
    }

    private func getJSON(path: String, auth: Bool = false) async throws -> [String: Any] {
        guard let url = URL(string: "\(AppConfig.apiBaseURL)/api/\(AppConfig.apiVersion)\(path)") else {
            throw AuthError.network
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        if auth, let token = KeychainHelper.shared.bearerToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return try await send(request: request, expectingEmptyResponse: false)
    }

    private func send(
        request: URLRequest,
        expectingEmptyResponse: Bool
    ) async throws -> [String: Any] {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw AuthError.network
        }
        guard let http = response as? HTTPURLResponse else {
            throw AuthError.network
        }
        switch http.statusCode {
        case 200..<300:
            if expectingEmptyResponse || data.isEmpty {
                return [:]
            }
            let parsed = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            return parsed ?? [:]
        case 401, 403:
            // Generic shape — backend deliberately returns identical
            // detail for every failure mode (wrong password, unknown
            // user, locked, MFA mismatch) to defeat account enumeration.
            // The UI maps this to "Invalid email or password."
            throw AuthError.invalidCredentials
        case 400..<500:
            // Other client errors (e.g. 400 reset-token-expired,
            // 400 MFA-code-mismatch). The caller layer (resetPassword,
            // verifyMfaSetup) re-classifies these to their domain-specific
            // error case.
            throw AuthError.invalidCredentials
        default:
            throw AuthError.network
        }
    }
}

// MARK: - Models

/// Token bundle returned by every successful auth call. The id-token
/// slot is populated with a copy of the access token to keep
/// ``KeychainHelper`` backwards-compatible — see ``AurionAuth.parseSession``.
struct AuthSession: Sendable {
    let accessToken: String
    let idToken: String
    let refreshToken: String
    let expiresAt: Date
}

// MARK: - Errors

/// Distilled auth-failure cases. Maps every backend response to one of a
/// small set of UI-facing categories so the LocalizedError descriptions
/// can stay PHI-free and account-enumeration-safe.
///
/// `invalidCredentials` deliberately collapses every "wrong-password /
/// unknown-user / locked / inactive" branch into the same message — the
/// backend does the same in its response body. Distinct categories exist
/// for state where revealing the specific failure mode is safe
/// (mfaCodeMismatch when the caller already passed the password gate,
/// passwordTooWeak when the caller is rotating their own password).
enum AuthError: LocalizedError, Equatable {
    case invalidCredentials
    case mfaCodeMismatch
    case passwordTooWeak
    case invalidResetToken
    case network
    case malformed

    var errorDescription: String? {
        switch self {
        case .invalidCredentials:
            return L("login.error.invalidCredentials")
        case .mfaCodeMismatch:
            return L("login.mfa.challenge.invalidCode")
        case .passwordTooWeak:
            return L("login.error.passwordTooWeak")
        case .invalidResetToken:
            return L("login.error.invalidResetToken")
        case .network:
            return L("login.error.network")
        case .malformed:
            return L("login.error.malformed")
        }
    }
}
