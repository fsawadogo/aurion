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
