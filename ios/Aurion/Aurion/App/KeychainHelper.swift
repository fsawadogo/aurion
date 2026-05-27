import Foundation
import Security

/// Keychain helper for sensitive credentials and on-device voice biometrics.
/// Voice embedding stored exclusively on-device — never transmitted to backend.
/// Auth token stored here so APIClient can attach it to every request.
final class KeychainHelper {
    static let shared = KeychainHelper()
    private let voiceEmbeddingKey = "aurion.physician.voice_embedding"
    private let authTokenKey = "aurion.auth.token"
    private let userIdKey = "aurion.auth.user_id"
    private let userRoleKey = "aurion.auth.user_role"
    private let userNameKey = "aurion.auth.user_name"
    // Cognito hosted-UI OAuth tokens. `authTokenKey` above stays as the
    // dev-only legacy slot; the Cognito-issued access token is the new
    // canonical Authorization-Bearer value for any non-local APP_ENV.
    private let cognitoAccessTokenKey  = "aurion.cognito.access_token"
    private let cognitoIDTokenKey      = "aurion.cognito.id_token"
    private let cognitoRefreshTokenKey = "aurion.cognito.refresh_token"
    private let cognitoExpiresAtKey    = "aurion.cognito.expires_at"

    private init() {}

    // MARK: - Voice Embedding

    func saveVoiceEmbedding(_ data: Data) { save(key: voiceEmbeddingKey, data: data) }
    func loadVoiceEmbedding() -> Data? { load(key: voiceEmbeddingKey) }
    func hasVoiceEmbedding() -> Bool { loadVoiceEmbedding() != nil }
    func deleteVoiceEmbedding() { delete(key: voiceEmbeddingKey) }

    // MARK: - Auth

    func saveAuthToken(_ token: String, userId: String, role: String, name: String) {
        saveString(key: authTokenKey, value: token)
        saveString(key: userIdKey, value: userId)
        saveString(key: userRoleKey, value: role)
        saveString(key: userNameKey, value: name)
    }

    func loadAuthToken() -> String? { loadString(key: authTokenKey) }
    func loadUserId() -> String? { loadString(key: userIdKey) }
    func loadUserRole() -> String? { loadString(key: userRoleKey) }
    func loadUserName() -> String? { loadString(key: userNameKey) }
    func hasAuthToken() -> Bool { loadAuthToken() != nil }

    func clearAuth() {
        delete(key: authTokenKey)
        delete(key: userIdKey)
        delete(key: userRoleKey)
        delete(key: userNameKey)
    }

    // MARK: - Cognito hosted-UI tokens

    /// Persist the full OAuth token set after a successful sign-in or
    /// refresh. `accessToken` rides on every API call; `refreshToken`
    /// is used by ``CognitoAuth.refreshIfNeeded()`` near expiry.
    func saveTokens(accessToken: String, idToken: String, refreshToken: String, expiresAt: Date) {
        saveString(key: cognitoAccessTokenKey, value: accessToken)
        saveString(key: cognitoIDTokenKey, value: idToken)
        if !refreshToken.isEmpty {
            saveString(key: cognitoRefreshTokenKey, value: refreshToken)
        }
        saveString(key: cognitoExpiresAtKey, value: String(expiresAt.timeIntervalSince1970))
    }

    /// Cognito access token — what APIClient sends as `Bearer …`.
    func getAccessToken() -> String? { loadString(key: cognitoAccessTokenKey) }

    /// Cognito id_token — carries the user's email + sub. Useful when
    /// a view needs to render the signed-in identity without a backend
    /// round-trip; the backend still validates JWTs via JWKS for every
    /// real authorisation decision.
    func getIDToken() -> String? { loadString(key: cognitoIDTokenKey) }

    /// The token to send as the API `Bearer …` header. Prefers the Cognito
    /// id_token (the backend validates it and reads the `email` claim on
    /// first sign-in); falls back to the legacy dev token for local-mode
    /// builds. SINGLE SOURCE OF TRUTH — every request path (APIClient and
    /// any raw URLSession upload) must use this so they can't drift. The
    /// transcription upload once read `loadAuthToken()` directly and 401'd
    /// after the switch to native Cognito login, which writes only the
    /// Cognito token slots; this helper prevents that class of bug.
    func bearerToken() -> String? { getIDToken() ?? loadAuthToken() }

    func getRefreshToken() -> String? { loadString(key: cognitoRefreshTokenKey) }

    /// True if the access token has either expired or is within 60s of
    /// expiring. Callers (APIClient) should refresh before issuing the
    /// request.
    var tokenIsStale: Bool {
        guard
            let raw = loadString(key: cognitoExpiresAtKey),
            let expiresAtSeconds = TimeInterval(raw)
        else { return true }
        let expiresAt = Date(timeIntervalSince1970: expiresAtSeconds)
        return expiresAt.timeIntervalSinceNow < 60
    }

    func hasValidSession() -> Bool {
        guard getAccessToken() != nil else { return false }
        return !tokenIsStale || getRefreshToken() != nil
    }

    func clearTokens() {
        delete(key: cognitoAccessTokenKey)
        delete(key: cognitoIDTokenKey)
        delete(key: cognitoRefreshTokenKey)
        delete(key: cognitoExpiresAtKey)
        // Belt-and-suspenders: nuke the dev-only auth slots too so a
        // sign-out doesn't leave a stale dev session lying around.
        clearAuth()
    }

    // MARK: - Internal

    private func saveString(key: String, value: String) {
        save(key: key, data: Data(value.utf8))
    }

    private func loadString(key: String) -> String? {
        load(key: key).flatMap { String(data: $0, encoding: .utf8) }
    }

    private func save(key: String, data: Data) {
        delete(key: key)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    private func load(key: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        return status == errSecSuccess ? result as? Data : nil
    }

    private func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
