import Foundation
import LocalAuthentication
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
    // Backend-issued JWT slots. Storage keys retain the historical
    // ``aurion.cognito.*`` prefix on purpose: ``saveTokens`` /
    // ``getAccessToken`` / ``getRefreshToken`` keep their contracts
    // byte-identical so no Keychain migration is required during the
    // AUTH-PIVOT cutover. The values stored here are now
    // backend-issued JWTs + opaque refresh tokens — not Cognito's
    // id_token / access_token — but the slot names are stable so a
    // mixed-cohort fleet (some pilots on backend JWTs, others
    // mid-cutover on Cognito) keeps working without divergence.
    private let cognitoAccessTokenKey  = "aurion.cognito.access_token"
    private let cognitoIDTokenKey      = "aurion.cognito.id_token"
    private let cognitoRefreshTokenKey = "aurion.cognito.refresh_token"
    private let cognitoExpiresAtKey    = "aurion.cognito.expires_at"
    // Biometric "remember me": the refresh token is stored under a separate
    // item gated by `.userPresence` (Face ID / Touch ID / passcode), so it
    // survives sign-out and can only be read after the user authenticates.
    // The email is a plain sibling item — a label for the button and a
    // prompt-free existence check.
    private let biometricRefreshTokenKey = "aurion.biometric.refresh_token"
    private let biometricEmailKey        = "aurion.biometric.email"

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

    // MARK: - Backend-issued tokens (post AUTH-PIVOT)

    /// Persist the full token set after a successful sign-in or
    /// refresh. `accessToken` rides on every API call; `refreshToken`
    /// is used by ``AurionAuth.refreshIfNeeded()`` near expiry.
    /// Signature preserved for backwards compatibility — see the
    /// comment block above the storage keys.
    func saveTokens(accessToken: String, idToken: String, refreshToken: String, expiresAt: Date) {
        saveString(key: cognitoAccessTokenKey, value: accessToken)
        saveString(key: cognitoIDTokenKey, value: idToken)
        if !refreshToken.isEmpty {
            saveString(key: cognitoRefreshTokenKey, value: refreshToken)
        }
        saveString(key: cognitoExpiresAtKey, value: String(expiresAt.timeIntervalSince1970))
    }

    /// Backend-issued access JWT — what APIClient sends as `Bearer …`.
    func getAccessToken() -> String? { loadString(key: cognitoAccessTokenKey) }

    /// Mirrors ``getAccessToken``. The legacy Cognito flow stored a
    /// separate id_token here; ``AurionAuth.parseSession`` writes the
    /// access token to both slots so ``bearerToken``'s fallback chain
    /// keeps working without a Keychain migration during cutover.
    func getIDToken() -> String? { loadString(key: cognitoIDTokenKey) }

    /// The token to send as the API `Bearer …` header. Prefers the
    /// id-token slot (populated with the backend access JWT in the
    /// post-AUTH-PIVOT flow; was the Cognito id_token historically);
    /// falls back to the legacy dev token for local-mode builds.
    /// SINGLE SOURCE OF TRUTH — every request path (APIClient and any
    /// raw URLSession upload) must use this so they can't drift.
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

    // MARK: - Biometric "remember me" credential

    /// Persist the refresh token behind a biometric/passcode gate plus the
    /// email as a plain label. Overwrites any prior saved login.
    func saveBiometricCredential(refreshToken: String, email: String) {
        guard !refreshToken.isEmpty else { return }
        saveProtected(key: biometricRefreshTokenKey, value: refreshToken)
        saveString(key: biometricEmailKey, value: email)
    }

    /// Read the saved refresh token using an already-authenticated
    /// `LAContext` (from ``BiometricAuth.authenticate``). Because the context
    /// has already evaluated, this read doesn't prompt again and returns
    /// quickly — safe to call on the main thread. Returns nil if nothing is
    /// saved or the context can't unlock the item.
    func loadBiometricRefreshToken(context: LAContext) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: biometricRefreshTokenKey,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecUseAuthenticationContext as String: context,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Email tied to the saved login — used to label the button and to test
    /// for existence without prompting for biometrics.
    func savedBiometricEmail() -> String? { loadString(key: biometricEmailKey) }
    func hasBiometricCredential() -> Bool { savedBiometricEmail() != nil }

    func clearBiometricCredential() {
        delete(key: biometricRefreshTokenKey)
        delete(key: biometricEmailKey)
    }

    // MARK: - Internal

    /// Store a value gated by `.userPresence` (biometry or device passcode).
    /// Reads of this item prompt the user; writes do not.
    private func saveProtected(key: String, value: String) {
        delete(key: key)
        guard let access = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            .userPresence,
            nil
        ) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessControl as String: access,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

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
