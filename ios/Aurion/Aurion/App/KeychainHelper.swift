import Foundation
import Security

/// Keychain helper for voice embedding storage.
/// Voice embedding stored exclusively on-device — never transmitted to backend.
final class KeychainHelper {
    static let shared = KeychainHelper()
    private let voiceEmbeddingKey = "aurion.physician.voice_embedding"

    private init() {}

    func saveVoiceEmbedding(_ data: Data) {
        delete(key: voiceEmbeddingKey)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: voiceEmbeddingKey,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    func loadVoiceEmbedding() -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: voiceEmbeddingKey,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        return status == errSecSuccess ? result as? Data : nil
    }

    func hasVoiceEmbedding() -> Bool {
        loadVoiceEmbedding() != nil
    }

    func deleteVoiceEmbedding() {
        delete(key: voiceEmbeddingKey)
    }

    private func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
