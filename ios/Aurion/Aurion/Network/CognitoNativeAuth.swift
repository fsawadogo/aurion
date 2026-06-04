import Foundation

/// Native (in-app, no ASWebAuthenticationSession) Cognito sign-in.
///
/// Calls Cognito's JSON `InitiateAuth` / `RespondToAuthChallenge` endpoints
/// directly with `USER_PASSWORD_AUTH`. The app client is already configured
/// for this flow (`infrastructure/cognito.tf` line 95 — `ALLOW_USER_PASSWORD_AUTH`).
///
/// Why a custom client (no AWS SDK):
///   - The AWS Mobile SDK for iOS is ~15 MB and pulls in a half-dozen
///     transitive dependencies for a flow that's two JSON POSTs.
///   - This file is ~150 LOC, exactly mirrors the hosted-UI path in
///     `CognitoAuth.swift` for token storage, and is easy to audit.
///
/// Trade-offs vs hosted UI:
///   - Lose Cognito's CAPTCHA, brute-force lockout, and password-leak
///     detection. Acceptable for the pilot (small, managed user set).
///   - The user pool's MFA setting still applies — if `mfa_configuration`
///     flips back to `ON`, `InitiateAuth` will return a
///     `SOFTWARE_TOKEN_MFA` challenge that this client doesn't handle yet.
///     Tracked alongside `AUR-COG-MFA-RESTORE`.
@MainActor
final class CognitoNativeAuth {
    static let shared = CognitoNativeAuth()

    /// Injected for tests; production always uses `URLSession.shared`.
    /// Kept `internal` (not `private`) so `@testable import Aurion` can
    /// swap a URLProtocol-based fake without ceremony.
    let urlSession: URLSession

    init(urlSession: URLSession = .shared) {
        self.urlSession = urlSession
    }

    private let endpoint = URL(string: "https://cognito-idp.\(AppConfig.cognitoRegion).amazonaws.com/")!

    // MARK: - Public API

    /// Result of an `InitiateAuth` (or `RespondToAuthChallenge`) call.
    /// Either tokens (signed in) or a challenge the caller must respond
    /// to with a separate screen.
    ///
    /// - `mfaRequired`: user has already enrolled TOTP. The MFA challenge
    ///    view collects the 6-digit code and calls `respondToTotpChallenge`.
    /// - `mfaSetupRequired`: pool policy is mandatory MFA and the user has
    ///    not enrolled yet. The setup view kicks off `signInForMfaSetup` to
    ///    get a fresh session, then `beginTotpSetup` for the shared secret,
    ///    then `verifyTotpSetup` to confirm and finish the sign-in.
    enum SignInOutcome {
        case authenticated(AuthSession)
        case newPasswordRequired(session: String, username: String)
        case mfaRequired(session: String, username: String)
        case mfaSetupRequired(session: String, username: String)
    }

    /// First-step return from a TOTP enrolment kickoff. The `secretCode`
    /// is the base32 shared secret the authenticator app needs; render it
    /// as both a copyable string AND a QR (`otpauth://…`). The optional
    /// `session` is non-nil only when enrolment was initiated mid-challenge
    /// (the `MFA_SETUP` branch) and the verify call must echo it back.
    struct TotpSetup {
        let secretCode: String
        let session: String?
    }

    /// Result of `VerifySoftwareToken`. We deliberately collapse Cognito's
    /// `Status` field into a tiny enum — the caller cares about success vs
    /// "wrong code, ask the user to try again", nothing more.
    enum TotpVerificationOutcome {
        case success(session: String?)
        case codeMismatch
    }

    /// Username + password → tokens (or challenge). Token bundle is
    /// persisted to ``KeychainHelper`` exactly the way the hosted-UI
    /// path does, so every downstream `APIClient.addAuth` keeps working.
    func signIn(email: String, password: String) async throws -> SignInOutcome {
        let body: [String: Any] = [
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": AppConfig.cognitoClientID,
            "AuthParameters": [
                "USERNAME": email,
                "PASSWORD": password,
            ],
        ]
        let raw = try await postJSON(target: "InitiateAuth", body: body)
        return try processAuthResult(raw, username: email)
    }

    /// Respond to a `NEW_PASSWORD_REQUIRED` challenge (first sign-in for
    /// any user the admin created with a temp password — every pilot
    /// physician hits this once).
    func completeNewPassword(
        username: String,
        newPassword: String,
        session: String
    ) async throws -> SignInOutcome {
        let body: [String: Any] = [
            "ChallengeName": "NEW_PASSWORD_REQUIRED",
            "ClientId": AppConfig.cognitoClientID,
            "Session": session,
            "ChallengeResponses": [
                "USERNAME": username,
                "NEW_PASSWORD": newPassword,
            ],
        ]
        let raw = try await postJSON(target: "RespondToAuthChallenge", body: body)
        return try processAuthResult(raw, username: username)
    }

    /// Respond to a `SOFTWARE_TOKEN_MFA` challenge — the daily sign-in
    /// path once the user is enrolled. The 6-digit `code` is from the
    /// authenticator app; the `session` token came from the failed
    /// `InitiateAuth` that returned the challenge.
    ///
    /// On success Cognito returns `AuthenticationResult` and we land in
    /// `.authenticated`, identical to the password-only happy path.
    func respondToTotpChallenge(
        session: String,
        username: String,
        code: String
    ) async throws -> SignInOutcome {
        let body: [String: Any] = [
            "ChallengeName": "SOFTWARE_TOKEN_MFA",
            "ClientId": AppConfig.cognitoClientID,
            "Session": session,
            "ChallengeResponses": [
                "USERNAME": username,
                "SOFTWARE_TOKEN_MFA_CODE": code,
            ],
        ]
        let raw = try await postJSON(target: "RespondToAuthChallenge", body: body)
        return try processAuthResult(raw, username: username)
    }

    /// Respond to an `MFA_SETUP` challenge. Cognito does not actually
    /// return tokens here — it returns a fresh `Session` that
    /// `AssociateSoftwareToken` (i.e. ``beginTotpSetup``) needs.
    ///
    /// We surface that session inside `.mfaSetupRequired` so the setup
    /// view's state machine is symmetric with the daily-login one — both
    /// branches start from a Cognito-issued session token.
    func signInForMfaSetup(
        session: String,
        username: String
    ) async throws -> SignInOutcome {
        let body: [String: Any] = [
            "ChallengeName": "MFA_SETUP",
            "ClientId": AppConfig.cognitoClientID,
            "Session": session,
            "ChallengeResponses": [
                "USERNAME": username,
            ],
        ]
        let raw = try await postJSON(target: "RespondToAuthChallenge", body: body)
        // Cognito's MFA_SETUP response: either AuthenticationResult
        // (if the pool didn't actually require setup — unlikely) OR a new
        // Session that the caller hands to AssociateSoftwareToken.
        if let auth = raw["AuthenticationResult"] as? [String: Any] {
            let parsed = try parseSession(auth)
            KeychainHelper.shared.saveTokens(
                accessToken: parsed.accessToken,
                idToken: parsed.idToken,
                refreshToken: parsed.refreshToken,
                expiresAt: parsed.expiresAt
            )
            return .authenticated(parsed)
        }
        let newSession = (raw["Session"] as? String) ?? ""
        return .mfaSetupRequired(session: newSession, username: username)
    }

    /// Kick off TOTP enrolment.
    ///
    /// Two callers:
    ///   - Mid-challenge (mandatory-MFA first sign-in): pass the `Session`
    ///     from ``signInForMfaSetup``. `accessToken` is nil.
    ///   - Post-signin opt-in (not used in this PR but symmetric for the
    ///     future Profile › Security flow): pass the `AccessToken`. `session`
    ///     is nil.
    ///
    /// Exactly one of `accessToken` / `session` must be non-nil; the
    /// `precondition` makes that contract loud at the call site.
    func beginTotpSetup(
        accessToken: String? = nil,
        session: String? = nil
    ) async throws -> TotpSetup {
        precondition(
            (accessToken != nil) != (session != nil),
            "beginTotpSetup requires exactly one of accessToken or session"
        )
        var body: [String: Any] = [:]
        if let accessToken {
            body["AccessToken"] = accessToken
        }
        if let session {
            body["Session"] = session
        }
        let raw = try await postJSON(target: "AssociateSoftwareToken", body: body)
        guard let secret = raw["SecretCode"] as? String, !secret.isEmpty else {
            throw NativeAuthError.malformed
        }
        let newSession = raw["Session"] as? String
        return TotpSetup(secretCode: secret, session: newSession)
    }

    /// Verify the user-entered 6-digit code against the freshly-associated
    /// TOTP secret. On `Status: SUCCESS` Cognito flips the user's
    /// `mfa_setting` to `SOFTWARE_TOKEN_MFA` and future sign-ins will
    /// challenge.
    ///
    /// As with ``beginTotpSetup``, exactly one of `accessToken` / `session`
    /// must be non-nil — caller passes whatever ``beginTotpSetup`` returned.
    func verifyTotpSetup(
        accessToken: String? = nil,
        session: String? = nil,
        code: String,
        friendlyDeviceName: String
    ) async throws -> TotpVerificationOutcome {
        precondition(
            (accessToken != nil) != (session != nil),
            "verifyTotpSetup requires exactly one of accessToken or session"
        )
        var body: [String: Any] = [
            "UserCode": code,
            "FriendlyDeviceName": friendlyDeviceName,
        ]
        if let accessToken {
            body["AccessToken"] = accessToken
        }
        if let session {
            body["Session"] = session
        }
        do {
            let raw = try await postJSON(target: "VerifySoftwareToken", body: body)
            let status = (raw["Status"] as? String) ?? ""
            switch status {
            case "SUCCESS":
                let nextSession = raw["Session"] as? String
                return .success(session: nextSession)
            case "ERROR":
                // Cognito's documented "the code didn't validate" outcome.
                // Surface as `.codeMismatch` so the UI prompts a retry
                // without bubbling a raw Cognito string.
                return .codeMismatch
            default:
                throw NativeAuthError.malformed
            }
        } catch NativeAuthError.cognito(let type, let message) {
            // CodeMismatchException is what Cognito uses when the TOTP
            // code is simply wrong; treat it like the SUCCESS=ERROR case so
            // the UI shows a single, non-leaky retry message.
            if type == "CodeMismatchException" {
                return .codeMismatch
            }
            throw NativeAuthError.cognito(type: type, message: message)
        }
    }

    /// Mint a fresh token set from a stored refresh token (biometric
    /// "remember me" sign-in). `REFRESH_TOKEN_AUTH` doesn't re-prompt MFA —
    /// the refresh token already represents an MFA-completed session — so the
    /// Face ID → signed-in path stays one tap even once MFA is restored.
    ///
    /// Cognito doesn't echo the refresh token back on this flow, so we
    /// re-persist the one we used into the canonical slot — otherwise the
    /// in-session refresh path (`CognitoAuth.refreshIfNeeded`) would have
    /// nothing to work with.
    func refreshSession(refreshToken: String) async throws -> SignInOutcome {
        let body: [String: Any] = [
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": AppConfig.cognitoClientID,
            "AuthParameters": ["REFRESH_TOKEN": refreshToken],
        ]
        let raw = try await postJSON(target: "InitiateAuth", body: body)
        let outcome = try processAuthResult(raw, username: "")
        if case .authenticated(let session) = outcome {
            KeychainHelper.shared.saveTokens(
                accessToken: session.accessToken,
                idToken: session.idToken,
                refreshToken: refreshToken,
                expiresAt: session.expiresAt
            )
        }
        return outcome
    }

    /// Local sign-out — drop the cached tokens. No Cognito round trip.
    /// Token revocation is handled by refresh-token expiry (30 days).
    /// The biometric "remember me" credential is intentionally NOT cleared
    /// here — it's a separate, user-managed convenience (Forget on the login
    /// screen or in Profile › Security).
    func signOut() {
        KeychainHelper.shared.clearTokens()
    }

    // MARK: - Internals

    /// Cognito's JSON API uses a custom `X-Amz-Target` header and the
    /// `application/x-amz-json-1.1` content type. No AWS request signing
    /// needed for these two endpoints — they're publicly callable.
    private func postJSON(target: String, body: [String: Any]) async throws -> [String: Any] {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/x-amz-json-1.1", forHTTPHeaderField: "Content-Type")
        request.setValue("AWSCognitoIdentityProviderService.\(target)", forHTTPHeaderField: "X-Amz-Target")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw NativeAuthError.network("Unexpected response shape")
        }

        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        guard (200..<300).contains(http.statusCode) else {
            // Cognito error envelope: {"__type":"NotAuthorizedException","message":"..."}
            let type = (json["__type"] as? String) ?? "CognitoError"
            let message = (json["message"] as? String) ?? "Sign-in failed."
            throw NativeAuthError.cognito(type: type, message: message)
        }
        return json
    }

    /// Decode either `AuthenticationResult` (success) or `ChallengeName`
    /// (challenge) from a Cognito response into our typed outcome.
    private func processAuthResult(
        _ json: [String: Any],
        username: String
    ) throws -> SignInOutcome {
        if let auth = json["AuthenticationResult"] as? [String: Any] {
            let session = try parseSession(auth)
            KeychainHelper.shared.saveTokens(
                accessToken: session.accessToken,
                idToken: session.idToken,
                refreshToken: session.refreshToken,
                expiresAt: session.expiresAt
            )
            return .authenticated(session)
        }

        let challengeName = (json["ChallengeName"] as? String) ?? ""
        let sessionToken = (json["Session"] as? String) ?? ""
        switch challengeName {
        case "NEW_PASSWORD_REQUIRED":
            return .newPasswordRequired(session: sessionToken, username: username)
        case "SOFTWARE_TOKEN_MFA":
            return .mfaRequired(session: sessionToken, username: username)
        case "MFA_SETUP":
            // First sign-in once the pool's mfa_configuration is ON: user
            // hasn't enrolled TOTP yet, the SetupView will run them through
            // AssociateSoftwareToken → VerifySoftwareToken → finish.
            return .mfaSetupRequired(session: sessionToken, username: username)
        default:
            throw NativeAuthError.unsupportedChallenge(name: challengeName)
        }
    }

    private func parseSession(_ auth: [String: Any]) throws -> AuthSession {
        guard
            let accessToken = auth["AccessToken"] as? String,
            let idToken = auth["IdToken"] as? String,
            let expiresIn = auth["ExpiresIn"] as? Int
        else {
            throw NativeAuthError.malformed
        }
        // Cognito only returns RefreshToken on the FIRST exchange; falling
        // back to whatever's in Keychain mirrors the hosted-UI behaviour.
        let refreshToken = (auth["RefreshToken"] as? String)
            ?? KeychainHelper.shared.getRefreshToken()
            ?? ""
        return AuthSession(
            accessToken: accessToken,
            idToken: idToken,
            refreshToken: refreshToken,
            expiresAt: Date().addingTimeInterval(TimeInterval(expiresIn))
        )
    }
}

enum NativeAuthError: LocalizedError {
    case network(String)
    case cognito(type: String, message: String)
    case malformed
    case unsupportedChallenge(name: String)

    var errorDescription: String? {
        switch self {
        case .network(let msg):
            return "Network error: \(msg)"
        case .cognito(let type, let message):
            // Surface Cognito's `__type` to the user only when it's
            // actionable — keep the generic `message` otherwise so we
            // don't leak whether a username exists (Cognito has
            // `prevent_user_existence_errors = ENABLED` for that reason).
            switch type {
            case "NotAuthorizedException":
                return "Incorrect email or password."
            case "UserNotConfirmedException":
                return "Account not yet confirmed. Contact your administrator."
            case "PasswordResetRequiredException":
                return "Password reset required. Contact your administrator."
            case "InvalidPasswordException":
                return message
            case "LimitExceededException", "TooManyRequestsException":
                return "Too many attempts. Wait a minute, then try again."
            case "CodeMismatchException":
                // The setup/verify path collapses this into
                // `.codeMismatch` before it reaches the user. This branch
                // exists only for the daily-login challenge path, where we
                // want a generic message that does NOT echo the entered
                // digits (no PHI / no auth-secret in surfaces).
                return "Incorrect code. Try again."
            case "ExpiredCodeException":
                return "Code expired. Enter the current one."
            case "EnableSoftwareTokenMFAException":
                // Cognito rejected the verify call — usually a TOTP secret
                // mismatch between AssociateSoftwareToken and the
                // authenticator app. Surface as a retry prompt.
                return "Couldn\u{2019}t enable two-factor. Re-scan the code and try again."
            case "SoftwareTokenMFANotFoundException":
                return "Two-factor isn\u{2019}t set up on this account. Contact your administrator."
            default:
                return message
            }
        case .malformed:
            return "Cognito returned a response we couldn't read."
        case .unsupportedChallenge(let name):
            return "Sign-in challenge '\(name)' isn't supported by this build."
        }
    }
}
