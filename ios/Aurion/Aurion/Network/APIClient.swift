import Foundation

/// API client — communicates with the FastAPI backend.
/// AI provider keys never called from iOS — always routed through backend.
final class APIClient: Sendable {
    static let shared = APIClient()
    private let baseURL: String

    private init() {
        self.baseURL = AppConfig.baseAPIPath
    }

    // MARK: - Session

    func createSession(specialty: String) async throws -> SessionResponse {
        return try await post(
            path: "/sessions",
            body: ["specialty": specialty]
        )
    }

    func confirmConsent(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/consent")
    }

    func startRecording(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/start")
    }

    func stopRecording(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/stop")
    }

    // MARK: - Notes

    func getStage1Note(sessionId: String) async throws -> NoteResponse {
        return try await get(path: "/notes/\(sessionId)/stage1")
    }

    func approveStage1(sessionId: String) async throws -> NoteApprovalResponse {
        return try await post(path: "/notes/\(sessionId)/approve-stage1")
    }

    func getFullNote(sessionId: String) async throws -> NoteResponse {
        return try await get(path: "/notes/\(sessionId)/full")
    }

    func approveFinalNote(sessionId: String) async throws -> NoteApprovalResponse {
        return try await post(path: "/notes/\(sessionId)/approve")
    }

    // MARK: - Export

    func exportNote(sessionId: String) async throws -> Data {
        let url = URL(string: "\(baseURL)/notes/\(sessionId)/export")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        let (data, _) = try await URLSession.shared.data(for: request)
        return data
    }

    // MARK: - Generic HTTP

    private func get<T: Decodable>(path: String) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        let request = URLRequest(url: url)
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable>(path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body = body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(T.self, from: data)
    }
}

// MARK: - Response Types

struct SessionResponse: Codable, Sendable {
    let id: String
    let clinicianId: String
    let specialty: String
    let state: String
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, specialty, state
        case clinicianId = "clinician_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct NoteResponse: Codable, Equatable, Sendable {
    let sessionId: String
    let stage: Int
    let version: Int
    let providerUsed: String
    let specialty: String
    let completenessScore: Double
    let sections: [NoteSectionResponse]

    enum CodingKeys: String, CodingKey {
        case stage, version, specialty, sections
        case sessionId = "session_id"
        case providerUsed = "provider_used"
        case completenessScore = "completeness_score"
    }
}

struct NoteSectionResponse: Codable, Equatable, Sendable {
    let id: String
    let title: String
    let status: String
    let claims: [NoteClaimResponse]
}

struct NoteClaimResponse: Codable, Equatable, Sendable {
    let id: String
    let text: String
    let sourceType: String
    let sourceId: String
    let sourceQuote: String

    enum CodingKeys: String, CodingKey {
        case id, text
        case sourceType = "source_type"
        case sourceId = "source_id"
        case sourceQuote = "source_quote"
    }
}

struct NoteApprovalResponse: Codable, Sendable {
    let sessionId: String
    let stage: Int
    let version: Int
    let approved: Bool
    let message: String

    enum CodingKeys: String, CodingKey {
        case stage, version, approved, message
        case sessionId = "session_id"
    }
}
