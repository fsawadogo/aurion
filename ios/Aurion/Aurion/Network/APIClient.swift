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

    func listSessions() async throws -> [SessionResponse] {
        return try await get(path: "/sessions")
    }

    func getSession(sessionId: String) async throws -> SessionResponse {
        return try await get(path: "/sessions/\(sessionId)")
    }

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
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        addAuth(&request)
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable>(path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        addAuth(&request)
        if let body = body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func performRequest(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await URLSession.shared.data(for: request)
        } catch let error as URLError {
            switch error.code {
            case .notConnectedToInternet, .networkConnectionLost:
                throw APIError.offline
            case .timedOut:
                throw APIError.timeout
            default:
                throw APIError.networkError(error.localizedDescription)
            }
        }
    }

    private func validateResponse(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        switch http.statusCode {
        case 200..<300: return
        case 401: throw APIError.unauthorized
        case 403: throw APIError.forbidden
        case 404: throw APIError.notFound
        case 409: throw APIError.conflict(String(data: data, encoding: .utf8) ?? "")
        case 500..<600: throw APIError.serverError(http.statusCode)
        default: throw APIError.serverError(http.statusCode)
        }
    }

    private func addAuth(_ request: inout URLRequest) {
        request.setValue("Bearer CLINICIAN", forHTTPHeaderField: "Authorization")
    }
}

// MARK: - API Error Types

enum APIError: LocalizedError {
    case offline
    case timeout
    case networkError(String)
    case unauthorized
    case forbidden
    case notFound
    case conflict(String)
    case serverError(Int)
    case decodingError(String)

    var errorDescription: String? {
        switch self {
        case .offline: return "No internet connection"
        case .timeout: return "Request timed out"
        case .networkError(let msg): return "Network error: \(msg)"
        case .unauthorized: return "Authentication required"
        case .forbidden: return "Access denied"
        case .notFound: return "Not found"
        case .conflict(let msg): return msg
        case .serverError(let code): return "Server error (\(code))"
        case .decodingError(let msg): return "Data error: \(msg)"
        }
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
