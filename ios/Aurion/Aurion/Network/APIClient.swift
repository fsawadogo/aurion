import Foundation

/// API client — communicates with the FastAPI backend.
/// AI provider keys never called from iOS — always routed through backend.
final class APIClient: Sendable {
    static let shared = APIClient()
    private let baseURL: String

    private init() {
        self.baseURL = AppConfig.baseAPIPath
    }

    // MARK: - Auth

    /// Calls the backend dev-login endpoint. Returns the LoginResponse on success;
    /// throws APIError on invalid credentials or network failure. Caller is
    /// responsible for persisting the token via KeychainHelper.
    func login(email: String, password: String) async throws -> LoginResponse {
        try await postAuth(path: "/auth/login", body: [
            "email": email,
            "password": password,
        ])
    }

    /// Creates a new CLINICIAN account and returns the same LoginResponse
    /// shape as `login` so the caller can drop straight into the app.
    func register(email: String, password: String, fullName: String) async throws -> LoginResponse {
        try await postAuth(path: "/auth/register", body: [
            "email": email,
            "password": password,
            "full_name": fullName,
        ])
    }

    private func postAuth(path: String, body: [String: Any]) async throws -> LoginResponse {
        guard let url = URL(string: "\(baseURL)\(path)") else {
            throw APIError.networkError("Invalid URL")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(LoginResponse.self, from: data)
    }

    // MARK: - Session

    func listSessions() async throws -> [SessionResponse] {
        return try await get(path: "/sessions")
    }

    func getSession(sessionId: String) async throws -> SessionResponse {
        return try await get(path: "/sessions/\(sessionId)")
    }

    func createSession(
        specialty: String,
        consultationType: String? = nil,
        encounterContext: String? = nil,
        outputLanguage: String = "en",
        encounterType: String = "doctor_patient",
        participants: [[String: Any]]? = nil,
        captureMode: String = "multimodal"
    ) async throws -> SessionResponse {
        var body: [String: Any] = [
            "specialty": specialty,
            "output_language": outputLanguage,
            "encounter_type": encounterType,
            "capture_mode": captureMode,
        ]
        if let consultationType { body["consultation_type"] = consultationType }
        if let encounterContext { body["encounter_context"] = encounterContext }
        if let participants { body["participants"] = participants }
        return try await post(path: "/sessions", body: body)
    }

    func updateSessionTemplate(sessionId: String, specialty: String) async throws -> SessionResponse {
        return try await patch(path: "/sessions/\(sessionId)/template", body: ["specialty": specialty])
    }

    func confirmConsent(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/consent")
    }

    func startRecording(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/start")
    }

    func pauseSession(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/pause")
    }

    func resumeSession(sessionId: String) async throws -> SessionResponse {
        return try await post(path: "/sessions/\(sessionId)/resume")
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

    /// Apply physician edits to the latest note version. The map keys are
    /// section ids ("physical_exam", "assessment", …); values are the new
    /// claim text. Backend creates a new immutable note version and returns it.
    func editNote(sessionId: String, edits: [String: String]) async throws -> NoteResponse {
        return try await patch(path: "/notes/\(sessionId)/edit", body: ["edits": edits])
    }

    // MARK: - Config

    /// Pulls the public AppConfig subset (providers, pipeline timing, feature flags).
    func getClientConfig() async throws -> ClientConfigResponse {
        return try await get(path: "/config")
    }

    // MARK: - Profile

    func getProfile() async throws -> PhysicianProfileResponse {
        return try await get(path: "/profile")
    }

    func updateProfile(_ updates: [String: Any]) async throws -> PhysicianProfileResponse {
        return try await put(path: "/profile", body: updates)
    }

    func getPreferredTemplates() async throws -> [TemplateResponse] {
        return try await get(path: "/profile/templates")
    }

    // MARK: - Frames

    /// Upload a single masked JPEG frame to the backend. Backend persists it
    /// to S3 at `frames/{session_id}/{timestamp_ms}.jpg` so the Stage 2 vision
    /// pipeline can match it against transcript trigger segments. Frames must
    /// be masked client-side first; iOS writes the masking_confirmed audit
    /// event before this call.
    @discardableResult
    func uploadFrame(sessionId: String, jpegData: Data, timestampMs: Int) async throws -> FrameUploadResponse {
        let url = URL(string: "\(baseURL)/frames/\(sessionId)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        addAuth(&request)

        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        let crlf = "\r\n".data(using: .utf8)!

        // timestamp_ms field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"timestamp_ms\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(timestampMs)".data(using: .utf8)!)
        body.append(crlf)

        // frame_file field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"frame_file\"; filename=\"frame.jpg\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(jpegData)
        body.append(crlf)

        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(FrameUploadResponse.self, from: data)
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

    private func mutate<T: Decodable>(method: String, path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = method
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

    private func patch<T: Decodable>(path: String, body: [String: Any]? = nil) async throws -> T {
        try await mutate(method: "PATCH", path: path, body: body)
    }

    private func put<T: Decodable>(path: String, body: [String: Any]? = nil) async throws -> T {
        try await mutate(method: "PUT", path: path, body: body)
    }

    private func post<T: Decodable>(path: String, body: [String: Any]? = nil) async throws -> T {
        try await mutate(method: "POST", path: path, body: body)
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
        if let token = KeychainHelper.shared.loadAuthToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
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
    let encounterType: String
    /// Echo of the `capture_mode` chosen at session creation. Defaults to
    /// `multimodal` for older sessions that pre-date the column so the iOS
    /// inbox can still render them without crashing on a missing key.
    let captureMode: String
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, specialty, state
        case clinicianId = "clinician_id"
        case encounterType = "encounter_type"
        case captureMode = "capture_mode"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        clinicianId = try c.decode(String.self, forKey: .clinicianId)
        specialty = try c.decode(String.self, forKey: .specialty)
        state = try c.decode(String.self, forKey: .state)
        encounterType = try c.decodeIfPresent(String.self, forKey: .encounterType) ?? "doctor_patient"
        captureMode = try c.decodeIfPresent(String.self, forKey: .captureMode) ?? "multimodal"
        createdAt = try c.decode(String.self, forKey: .createdAt)
        updatedAt = try c.decode(String.self, forKey: .updatedAt)
    }

    init(
        id: String,
        clinicianId: String,
        specialty: String,
        state: String,
        encounterType: String = "doctor_patient",
        captureMode: String = "multimodal",
        createdAt: String,
        updatedAt: String
    ) {
        self.id = id
        self.clinicianId = clinicianId
        self.specialty = specialty
        self.state = state
        self.encounterType = encounterType
        self.captureMode = captureMode
        self.createdAt = createdAt
        self.updatedAt = updatedAt
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

struct AlliedHealthMember: Codable, Sendable, Equatable {
    let name: String
    let role: String
}

struct PhysicianProfileResponse: Codable, Sendable {
    let clinicianId: String
    let displayName: String
    let practiceType: String?
    let primarySpecialty: String
    let preferredTemplates: [String]
    let consultationTypes: [String]
    let alliedHealthTeam: [AlliedHealthMember]
    let outputLanguage: String
    /// Recording preferences set during onboarding's profile setup. Decoded
    /// with defaults so a backend running an older schema doesn't break the
    /// iOS profile fetch — these become authoritative once the column has
    /// shipped to every environment.
    let autoUpload: Bool
    let retentionDays: Int
    let consentReprompt: String

    enum CodingKeys: String, CodingKey {
        case clinicianId = "clinician_id"
        case displayName = "display_name"
        case practiceType = "practice_type"
        case primarySpecialty = "primary_specialty"
        case preferredTemplates = "preferred_templates"
        case consultationTypes = "consultation_types"
        case alliedHealthTeam = "allied_health_team"
        case outputLanguage = "output_language"
        case autoUpload = "auto_upload"
        case retentionDays = "retention_days"
        case consentReprompt = "consent_reprompt"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        clinicianId = try c.decode(String.self, forKey: .clinicianId)
        displayName = try c.decode(String.self, forKey: .displayName)
        practiceType = try c.decodeIfPresent(String.self, forKey: .practiceType)
        primarySpecialty = try c.decode(String.self, forKey: .primarySpecialty)
        preferredTemplates = try c.decode([String].self, forKey: .preferredTemplates)
        consultationTypes = try c.decode([String].self, forKey: .consultationTypes)
        alliedHealthTeam = (try? c.decode([AlliedHealthMember].self, forKey: .alliedHealthTeam)) ?? []
        outputLanguage = try c.decode(String.self, forKey: .outputLanguage)
        autoUpload = try c.decodeIfPresent(Bool.self, forKey: .autoUpload) ?? true
        retentionDays = try c.decodeIfPresent(Int.self, forKey: .retentionDays) ?? 7
        consentReprompt = try c.decodeIfPresent(String.self, forKey: .consentReprompt) ?? "every_session"
    }
}

struct TemplateSectionResponse: Codable, Sendable {
    let id: String
    let title: String
    let required: Bool
    let description: String
}

struct TemplateResponse: Codable, Sendable {
    let key: String
    let displayName: String
    let sections: [TemplateSectionResponse]

    enum CodingKeys: String, CodingKey {
        case key, sections
        case displayName = "display_name"
    }
}

struct FrameUploadResponse: Codable, Sendable {
    let sessionId: String
    let s3Key: String
    let bytesUploaded: Int

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case s3Key = "s3_key"
        case bytesUploaded = "bytes_uploaded"
    }
}

struct LoginResponse: Codable, Sendable {
    let accessToken: String
    let tokenType: String
    let role: String
    let userId: String
    let fullName: String

    enum CodingKeys: String, CodingKey {
        case role
        case accessToken = "access_token"
        case tokenType = "token_type"
        case userId = "user_id"
        case fullName = "full_name"
    }
}

// MARK: - Client Config

struct ClientProvidersResponse: Codable, Sendable {
    let transcription: String
    let noteGeneration: String
    let vision: String

    enum CodingKeys: String, CodingKey {
        case transcription, vision
        case noteGeneration = "note_generation"
    }
}

struct ClientPipelineResponse: Codable, Sendable {
    let stage1SkipWindowSeconds: Int
    let frameWindowClinicMs: Int
    let frameWindowProceduralMs: Int
    let screenCaptureFps: Int
    let videoCaptureFps: Int

    enum CodingKeys: String, CodingKey {
        case stage1SkipWindowSeconds = "stage1_skip_window_seconds"
        case frameWindowClinicMs = "frame_window_clinic_ms"
        case frameWindowProceduralMs = "frame_window_procedural_ms"
        case screenCaptureFps = "screen_capture_fps"
        case videoCaptureFps = "video_capture_fps"
    }
}

struct ClientFeatureFlagsResponse: Codable, Sendable {
    let screenCaptureEnabled: Bool
    let noteVersioningEnabled: Bool
    let sessionPauseResumeEnabled: Bool
    let perSessionProviderOverride: Bool
    let metaWearablesEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case screenCaptureEnabled = "screen_capture_enabled"
        case noteVersioningEnabled = "note_versioning_enabled"
        case sessionPauseResumeEnabled = "session_pause_resume_enabled"
        case perSessionProviderOverride = "per_session_provider_override"
        case metaWearablesEnabled = "meta_wearables_enabled"
    }
}

struct ClientConfigResponse: Codable, Sendable {
    let providers: ClientProvidersResponse
    let pipeline: ClientPipelineResponse
    let featureFlags: ClientFeatureFlagsResponse

    enum CodingKeys: String, CodingKey {
        case providers, pipeline
        case featureFlags = "feature_flags"
    }
}
