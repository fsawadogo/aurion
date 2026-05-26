import AuthenticationServices
import CryptoKit
import Foundation

/// Cognito hosted-UI OAuth client. Opens the Cognito sign-in page in
/// Apple's secure ``ASWebAuthenticationSession`` (sandboxed Safari that
/// can't be sniffed by other apps), captures the auth code on the
/// `aurion://oauth-callback` redirect, and exchanges it for tokens at
/// `/oauth2/token` with PKCE.
///
/// Cognito drives the entire password + TOTP MFA + first-time enrollment
/// flow inside its hosted UI — no MFA code needs to live in the iOS app.
///
/// Tokens are stored in ``KeychainHelper``: the access token rides on
/// every API request as `Authorization: Bearer ...`, the refresh token
/// is held for ``refreshIfNeeded()`` later.
@MainActor
final class CognitoAuth: NSObject {
    static let shared = CognitoAuth()

    private override init() {}

    // MARK: - Sign in (Authorization Code with PKCE)

    /// Launch the hosted UI, complete OAuth, persist tokens. Throws if
    /// the user cancels or any step fails. On success, the access token
    /// is in ``KeychainHelper`` and the caller can read it via
    /// ``KeychainHelper.shared.getAuthToken()``.
    func signIn() async throws -> AuthSession {
        // PKCE: generate a 32-byte URL-safe code_verifier and its SHA-256
        // challenge. Cognito tolerates verifier between 43..128 chars.
        let verifier = Self.makeCodeVerifier()
        let challenge = Self.codeChallenge(for: verifier)

        // 1. Authorize — opens the hosted UI in the secure webview.
        let code = try await requestAuthorizationCode(challenge: challenge)

        // 2. Exchange — POST /oauth2/token with the verifier.
        let session = try await exchangeCodeForTokens(code: code, verifier: verifier)

        // 3. Persist — APIClient reads from Keychain on every call.
        KeychainHelper.shared.saveTokens(
            accessToken: session.accessToken,
            idToken: session.idToken,
            refreshToken: session.refreshToken,
            expiresAt: session.expiresAt
        )
        return session
    }

    // MARK: - Sign out

    /// Local sign-out — clear Keychain. Cognito session cookie inside
    /// ASWebAuthenticationSession is sandboxed per-call; it's dropped
    /// automatically. A hosted-UI ``/logout`` round trip is optional
    /// and only needed if you want to revoke the refresh token; for the
    /// pilot we skip it.
    func signOut() {
        KeychainHelper.shared.clearTokens()
    }

    // MARK: - Internals

    private func requestAuthorizationCode(challenge: String) async throws -> String {
        var components = URLComponents(string: "\(AppConfig.cognitoHostedUIBase)/oauth2/authorize")!
        components.queryItems = [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: AppConfig.cognitoClientID),
            URLQueryItem(name: "redirect_uri", value: AppConfig.cognitoCallbackURL),
            URLQueryItem(name: "scope", value: AppConfig.cognitoScopes.joined(separator: " ")),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
        ]
        guard let authorizeURL = components.url else { throw AuthError.invalidAuthorizeURL }

        // ASWebAuthenticationSession is the only Apple-blessed way to
        // run an OAuth flow that survives App Store review. It opens a
        // sandboxed Safari instance with no cross-app cookie access.
        return try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(
                url: authorizeURL,
                callbackURLScheme: AppConfig.cognitoCallbackScheme
            ) { callbackURL, error in
                if let error {
                    // .canceledLogin = user closed the sheet — common,
                    // surface as the dedicated case so the UI can show
                    // "Sign in cancelled" rather than a generic failure.
                    if (error as? ASWebAuthenticationSessionError)?.code == .canceledLogin {
                        continuation.resume(throwing: AuthError.userCancelled)
                    } else {
                        continuation.resume(throwing: AuthError.webAuthFailed(underlying: error))
                    }
                    return
                }
                guard
                    let url = callbackURL,
                    let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
                    let code = components.queryItems?.first(where: { $0.name == "code" })?.value
                else {
                    continuation.resume(throwing: AuthError.missingAuthCode)
                    return
                }
                continuation.resume(returning: code)
            }
            session.presentationContextProvider = self
            // Keep the cookie store ephemeral so a previous physician's
            // session can't auto-populate on a shared iPad.
            session.prefersEphemeralWebBrowserSession = true
            session.start()
        }
    }

    private func exchangeCodeForTokens(code: String, verifier: String) async throws -> AuthSession {
        var request = URLRequest(url: URL(string: "\(AppConfig.cognitoHostedUIBase)/oauth2/token")!)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        let formItems: [URLQueryItem] = [
            URLQueryItem(name: "grant_type", value: "authorization_code"),
            URLQueryItem(name: "client_id", value: AppConfig.cognitoClientID),
            URLQueryItem(name: "code", value: code),
            URLQueryItem(name: "redirect_uri", value: AppConfig.cognitoCallbackURL),
            URLQueryItem(name: "code_verifier", value: verifier),
        ]
        var body = URLComponents()
        body.queryItems = formItems
        request.httpBody = body.percentEncodedQuery?.data(using: .utf8)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard
            let http = response as? HTTPURLResponse,
            (200..<300).contains(http.statusCode)
        else {
            let bodyText = String(data: data, encoding: .utf8) ?? "<no body>"
            throw AuthError.tokenExchangeFailed(detail: bodyText)
        }

        struct TokenResponse: Decodable {
            let access_token: String
            let id_token: String
            let refresh_token: String?
            let expires_in: Int
            let token_type: String
        }
        let decoded = try JSONDecoder().decode(TokenResponse.self, from: data)
        return AuthSession(
            accessToken: decoded.access_token,
            idToken: decoded.id_token,
            // Cognito only returns a refresh_token on the FIRST exchange.
            // Subsequent refresh-token calls re-use the same one and
            // omit it from the response — fall back to whatever's in
            // Keychain in that case.
            refreshToken: decoded.refresh_token ?? KeychainHelper.shared.getRefreshToken() ?? "",
            expiresAt: Date().addingTimeInterval(TimeInterval(decoded.expires_in))
        )
    }

    // MARK: - Refresh

    /// Trade the stored refresh token for a fresh access token. Call
    /// before any API request if ``KeychainHelper.shared.tokenIsStale``
    /// reports true. Returns the new ``AuthSession``; tokens are also
    /// persisted to Keychain.
    func refreshIfNeeded() async throws -> AuthSession? {
        guard let refreshToken = KeychainHelper.shared.getRefreshToken() else { return nil }

        var request = URLRequest(url: URL(string: "\(AppConfig.cognitoHostedUIBase)/oauth2/token")!)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        var body = URLComponents()
        body.queryItems = [
            URLQueryItem(name: "grant_type", value: "refresh_token"),
            URLQueryItem(name: "client_id", value: AppConfig.cognitoClientID),
            URLQueryItem(name: "refresh_token", value: refreshToken),
        ]
        request.httpBody = body.percentEncodedQuery?.data(using: .utf8)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard
            let http = response as? HTTPURLResponse,
            (200..<300).contains(http.statusCode)
        else {
            // 401 here means the refresh token was revoked or has
            // expired (30 days). Clear local state so ContentView
            // routes back to LoginView.
            KeychainHelper.shared.clearTokens()
            throw AuthError.refreshFailed
        }

        struct RefreshResponse: Decodable {
            let access_token: String
            let id_token: String
            let expires_in: Int
            let token_type: String
        }
        let decoded = try JSONDecoder().decode(RefreshResponse.self, from: data)
        let session = AuthSession(
            accessToken: decoded.access_token,
            idToken: decoded.id_token,
            refreshToken: refreshToken,
            expiresAt: Date().addingTimeInterval(TimeInterval(decoded.expires_in))
        )
        KeychainHelper.shared.saveTokens(
            accessToken: session.accessToken,
            idToken: session.idToken,
            refreshToken: session.refreshToken,
            expiresAt: session.expiresAt
        )
        return session
    }

    // MARK: - PKCE helpers

    private static func makeCodeVerifier() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64URLEncodedString()
    }

    private static func codeChallenge(for verifier: String) -> String {
        let hash = SHA256.hash(data: Data(verifier.utf8))
        return Data(hash).base64URLEncodedString()
    }
}

// MARK: - Models

struct AuthSession {
    let accessToken: String
    let idToken: String
    let refreshToken: String
    let expiresAt: Date
}

enum AuthError: LocalizedError {
    case invalidAuthorizeURL
    case userCancelled
    case webAuthFailed(underlying: Error)
    case missingAuthCode
    case tokenExchangeFailed(detail: String)
    case refreshFailed

    var errorDescription: String? {
        switch self {
        case .invalidAuthorizeURL:                  return "Could not build Cognito authorize URL."
        case .userCancelled:                        return "Sign-in cancelled."
        case .webAuthFailed(let underlying):        return "Sign-in failed: \(underlying.localizedDescription)"
        case .missingAuthCode:                      return "Sign-in returned no authorization code."
        case .tokenExchangeFailed(let detail):      return "Token exchange failed: \(detail)"
        case .refreshFailed:                        return "Session expired. Please sign in again."
        }
    }
}

// MARK: - ASWebAuthenticationSession presentation host

extension CognitoAuth: ASWebAuthenticationPresentationContextProviding {
    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        // ASWebAuthenticationSession invokes this on the main thread per
        // Apple's contract. A previous `DispatchQueue.main.sync` wrapper
        // here deadlocked main → watchdog SIGKILL → app vanished the
        // moment the user tapped Sign in. We branch on Thread.isMainThread
        // so we stay safe even if Apple ever calls it off-main.
        if Thread.isMainThread {
            return Self.keyWindowAnchor()
        }
        return DispatchQueue.main.sync { Self.keyWindowAnchor() }
    }

    // `nonisolated` because the enclosing class is @MainActor but this
    // helper is invoked from the nonisolated protocol callback above.
    // ASWebAuthenticationSession's contract is to call us on main, so
    // touching UIApplication here is safe at runtime even though Swift
    // can't statically prove it.
    private nonisolated static func keyWindowAnchor() -> ASPresentationAnchor {
        // Return the key window — the only sensible anchor for a sheet
        // that needs to overlay the foreground app. UIScene-based apps
        // can have multiple windows; first connected scene with a
        // .foregroundActive state is the one the user is looking at.
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }
        return scene?.windows.first { $0.isKeyWindow } ?? ASPresentationAnchor()
    }
}

// MARK: - Base64 URL encoding (RFC 4648 §5)

private extension Data {
    func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
