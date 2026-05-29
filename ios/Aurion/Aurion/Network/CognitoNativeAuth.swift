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
    private init() {}

    private let endpoint = URL(string: "https://cognito-idp.\(AppConfig.cognitoRegion).amazonaws.com/")!

    // MARK: - Public API

    /// Result of an `InitiateAuth` call. Either tokens (signed in) or a
    /// challenge the caller must respond to with a separate screen.
    enum SignInOutcome {
        case authenticated(AuthSession)
        case newPasswordRequired(session: String, username: String)
        case mfaRequired(session: String, username: String)
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

        let (data, response) = try await URLSession.shared.data(for: request)
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
