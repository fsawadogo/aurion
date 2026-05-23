import Foundation

/// Environment-based configuration for API endpoints.
enum AppConfig {
    #if DEBUG
    // Local development. Simulator hits the loopback; physical device
    // on the Mac's LAN reads through the host IP.
    #if targetEnvironment(simulator)
    static let apiBaseURL = "http://localhost:8080"
    static let wsBaseURL  = "ws://localhost:8080"
    #else
    static let apiBaseURL = "http://10.0.0.225:8080"
    static let wsBaseURL  = "ws://10.0.0.225:8080"
    #endif
    #else
    // Release builds (TestFlight + App Store). Pilot points at the
    // dev AWS infrastructure — Phase 4/5 will split this into TestFlight
    // → dev vs App Store → prod via build configurations. For now,
    // both downstream targets land here.
    static let apiBaseURL = "https://api-dev.aurionclinical.com"
    static let wsBaseURL  = "wss://api-dev.aurionclinical.com"
    #endif

    static let apiVersion = "v1"
    static var baseAPIPath: String { "\(apiBaseURL)/api/\(apiVersion)" }

    /// Hard wall-clock cap for Stage 1 (record-stop → note-delivered).
    /// Matches the MVP SLA. Should move to `RemoteConfig.pipeline` once
    /// the backend exposes a `stage1_latency_ms_target` field.
    static let stage1TimeoutSeconds: TimeInterval = 30

    // MARK: - Cognito (hosted UI OAuth)
    //
    // iOS opens the hosted login page in ASWebAuthenticationSession,
    // Cognito handles the password + TOTP MFA flow, then redirects back
    // to `${callbackScheme}://oauth-callback` with an auth code that
    // ``CognitoAuth`` exchanges for tokens.

    /// Public Cognito app-client ID. No client secret — required for
    /// public clients per Cognito docs.
    static let cognitoClientID = "78kr08fp0q4gmgm5qpu65voq5j"

    /// Hosted UI base URL. Sign-in lives at `/oauth2/authorize`,
    /// token exchange at `/oauth2/token`, signout at `/logout`.
    static let cognitoHostedUIBase = "https://aurion-dev.auth.ca-central-1.amazoncognito.com"

    /// URL scheme the hosted UI redirects back to. Registered in
    /// `Info.plist`'s `CFBundleURLTypes` (synthesised via
    /// INFOPLIST_KEY_*; see ecs.tf for the matching backend env vars).
    static let cognitoCallbackScheme = "aurion"
    static let cognitoCallbackURL = "\(cognitoCallbackScheme)://oauth-callback"
    static let cognitoLogoutCallbackURL = "\(cognitoCallbackScheme)://oauth-logout"

    /// OAuth scopes — `openid` is required for Cognito to issue an
    /// id_token; `email` + `profile` give us the basic user info the
    /// backend reads on first sign-in to provision a UserModel row.
    /// `aws.cognito.signin.user.admin` lets the access token call
    /// Cognito's own /users API (used for MFA enrollment confirm).
    static let cognitoScopes = ["openid", "email", "profile", "aws.cognito.signin.user.admin"]
}
