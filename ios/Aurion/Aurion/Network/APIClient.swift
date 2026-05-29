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

    /// Calls `/auth/me` with the current Bearer token. Backend validates
    /// the Cognito JWT, finds or auto-provisions the matching UserModel
    /// row, and returns the canonical identity. Used as the post-sign-in
    /// handshake by ``LoginView`` so the SwiftUI app knows who you are
    /// without parsing the JWT itself.
    func fetchCurrentUser() async throws -> CurrentUserResponse {
        try await get(path: "/auth/me")
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

    func confirmConsent(sessionId: String, method: ConsentMethod) async throws -> SessionResponse {
        return try await post(
            path: "/sessions/\(sessionId)/consent",
            body: ["consent_method": method.rawValue]
        )
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

    /// Upload a recorded WAV for transcription + Stage 1 note generation,
    /// used by `OfflineUploadQueue` to drain deferred encounters. Distinct
    /// from the interactive `SessionManager.submitAudio` path, which carries
    /// its own SLA timeout and drives the live processing UI; this is a
    /// fire-and-wait background call. Throws `APIError` (offline/timeout →
    /// keep queued; other → bounded retry) so the queue can classify failures.
    /// The transcription runs server-side synchronously, hence the long timeout.
    func uploadAudioForTranscription(sessionId: String, audio: Data) async throws {
        let url = URL(string: "\(baseURL)/transcription/\(sessionId)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 180
        let boundary = UUID().uuidString
        request.setValue(
            "multipart/form-data; boundary=\(boundary)",
            forHTTPHeaderField: "Content-Type"
        )
        addAuth(&request)
        var builder = MultipartBuilder(boundary: boundary)
        builder.appendFile(
            "audio_file",
            filename: "recording.wav",
            mime: "audio/wav",
            data: audio
        )
        request.httpBody = builder.finish()
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
    }

    /// Permanently delete a session and its data (clinician-scoped on the
    /// backend — you can only discard your own). Returns 204 with no body, so
    /// it goes through a non-decoding path rather than `mutate`.
    func discardSession(sessionId: String) async throws {
        let url = URL(string: "\(baseURL)/sessions/\(sessionId)")!
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 30
        addAuth(&request)
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
    }

    // MARK: - Notes

    func getStage1Note(sessionId: String) async throws -> NoteResponse {
        return try await get(path: "/notes/\(sessionId)/stage1")
    }

    func approveStage1(sessionId: String) async throws -> NoteApprovalResponse {
        return try await post(path: "/notes/\(sessionId)/approve-stage1")
    }

    /// Poll the async Stage 2 job status. The endpoint always returns 200;
    /// status is `no_job` until Stage 1 is approved, then transitions
    /// through `pending` → `running` → `completed` | `failed`.
    func getStage2Status(sessionId: String) async throws -> Stage2StatusResponse {
        return try await get(path: "/notes/\(sessionId)/stage2-status")
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
    /// pipeline can match it against transcript trigger segments.
    ///
    /// P0-02: every upload carries a masking proof (`frame_type`,
    /// `masking_status`, counts). The backend rejects uploads without it.
    /// `masking_status` is fixed to `"success"` because failed/skipped
    /// frames are quarantined on-device and never reach this method.
    @discardableResult
    func uploadFrame(
        sessionId: String,
        jpegData: Data,
        timestampMs: Int,
        frameType: String,
        facesDetected: Int,
        phiRegionsRedacted: Int
    ) async throws -> FrameUploadResponse {
        var (request, builder) = makeMultipartUpload(url: URL(string: "\(baseURL)/frames/\(sessionId)")!)
        builder.appendField("timestamp_ms", "\(timestampMs)")
        builder.appendField("frame_type", frameType)
        builder.appendField("masking_status", "success")
        builder.appendField("faces_detected", "\(facesDetected)")
        builder.appendField("phi_regions_redacted", "\(phiRegionsRedacted)")
        builder.appendFile("frame_file", filename: "frame.jpg", mime: "image/jpeg", data: jpegData)
        request.httpBody = builder.finish()

        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(FrameUploadResponse.self, from: data)
    }

    // MARK: - Screen Capture (M-08)

    /// Upload a single redacted screen JPEG to the backend OCR pipeline.
    /// Backend persists to S3, runs OCR + classification, and merges any
    /// extracted lab values / imaging metadata into the session's note
    /// as screen-sourced claims. Same masking-proof contract as
    /// `uploadFrame` (P0-02).
    @discardableResult
    func uploadScreenFrame(
        sessionId: String,
        jpegData: Data,
        timestampMs: Int,
        phiRegionsRedacted: Int
    ) async throws -> ScreenUploadResponse {
        var (request, builder) = makeMultipartUpload(url: URL(string: "\(baseURL)/screen/\(sessionId)")!)
        builder.appendField("timestamp_ms", "\(timestampMs)")
        builder.appendField("frame_type", "screen")
        builder.appendField("masking_status", "success")
        builder.appendField("faces_detected", "0")
        builder.appendField("phi_regions_redacted", "\(phiRegionsRedacted)")
        builder.appendFile("frame_file", filename: "screen.jpg", mime: "image/jpeg", data: jpegData)
        request.httpBody = builder.finish()

        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(ScreenUploadResponse.self, from: data)
    }

    // MARK: - Multipart helper

    /// Single source of truth for the boundary: produces a POST request
    /// (method, auth, timeout, Content-Type with boundary) paired with a
    /// ``MultipartBuilder`` that writes against the same boundary.
    private func makeMultipartUpload(url: URL) -> (URLRequest, MultipartBuilder) {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        addAuth(&request)
        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue(
            "multipart/form-data; boundary=\(boundary)",
            forHTTPHeaderField: "Content-Type"
        )
        return (request, MultipartBuilder(boundary: boundary))
    }

    // MARK: - Speaker Tags

    /// Apply on-device speaker tags to a session's persisted transcript.
    /// The voice embedding stays in Keychain — only labels and
    /// confidences cross the wire.
    @discardableResult
    func patchSpeakerTags(
        sessionId: String,
        tags: [SpeakerTagRequest]
    ) async throws -> SpeakerTagApplyResponse {
        let url = URL(string: "\(baseURL)/transcription/\(sessionId)/speakers")!
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        addAuth(&request)
        request.httpBody = try JSONEncoder().encode(SpeakerTagBatch(tags: tags))
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(SpeakerTagApplyResponse.self, from: data)
    }

    /// Resolve a single Stage 2 visual conflict. The new note version is
    /// returned so the UI can render the resolved state without a refetch.
    @discardableResult
    func resolveConflict(
        sessionId: String,
        claimId: String,
        action: ConflictResolutionAction,
        resolutionText: String? = nil
    ) async throws -> NoteResponse {
        var body: [String: Any] = ["action": action.rawValue]
        if let text = resolutionText { body["resolution_text"] = text }
        return try await patch(path: "/notes/\(sessionId)/conflicts/\(claimId)/resolve", body: body)
    }

    // MARK: - Export

    /// Server-side DOCX generation. Kept for the web portal flow; the
    /// mobile MVP path uses on-device generation + `recordExportAudit`
    /// instead so nothing crosses the wire on export.
    func exportNote(sessionId: String) async throws -> Data {
        let url = URL(string: "\(baseURL)/notes/\(sessionId)/export")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        let (data, _) = try await URLSession.shared.data(for: request)
        return data
    }

    /// Record an on-device export. Called after the local file has been
    /// generated and offered to the share sheet — no bytes are sent.
    @discardableResult
    func recordExportAudit(
        sessionId: String,
        format: String,
        bytesProduced: Int
    ) async throws -> ExportAuditResponse {
        return try await post(
            path: "/notes/\(sessionId)/export-audit",
            body: ["format": format, "bytes_produced": bytesProduced]
        )
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
            case .notConnectedToInternet, .networkConnectionLost,
                 .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
                // Treat "backend unreachable" the same as "no network" — both
                // mean the request can't land, so the offline queue should
                // keep the encounter and retry rather than dropping it.
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
        // Canonical bearer-token selection lives in KeychainHelper so raw
        // URLSession upload paths (e.g. the transcription multipart POST)
        // use the exact same token and can't drift out of sync.
        let token = KeychainHelper.shared.bearerToken()
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
    }
}

// MARK: - Multipart Form Data Builder

/// Builds an HTTP multipart/form-data body in PKWARE-style chunks.
///
/// Mirrors what the two upload endpoints (frame and screen) used to inline.
/// Construct one per request with a fresh boundary, append fields and
/// files in order, then call ``finish()`` to get the final ``Data``.
struct MultipartBuilder {
    let boundary: String
    private var body = Data()
    private static let crlf = "\r\n".data(using: .utf8)!

    init(boundary: String) {
        self.boundary = boundary
    }

    mutating func appendField(_ name: String, _ value: String) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append(value.data(using: .utf8)!)
        body.append(Self.crlf)
    }

    mutating func appendFile(_ name: String, filename: String, mime: String, data: Data) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n"
                .data(using: .utf8)!
        )
        body.append("Content-Type: \(mime)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append(Self.crlf)
    }

    func finish() -> Data {
        var final = body
        final.append("--\(boundary)--\r\n".data(using: .utf8)!)
        return final
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
    let physicianEdited: Bool
    let originalText: String?

    init(
        id: String,
        text: String,
        sourceType: String,
        sourceId: String,
        sourceQuote: String,
        physicianEdited: Bool = false,
        originalText: String? = nil
    ) {
        self.id = id
        self.text = text
        self.sourceType = sourceType
        self.sourceId = sourceId
        self.sourceQuote = sourceQuote
        self.physicianEdited = physicianEdited
        self.originalText = originalText
    }

    enum CodingKeys: String, CodingKey {
        case id, text
        case sourceType = "source_type"
        case sourceId = "source_id"
        case sourceQuote = "source_quote"
        case physicianEdited = "physician_edited"
        case originalText = "original_text"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        text = try c.decode(String.self, forKey: .text)
        sourceType = try c.decode(String.self, forKey: .sourceType)
        sourceId = try c.decode(String.self, forKey: .sourceId)
        sourceQuote = try c.decodeIfPresent(String.self, forKey: .sourceQuote) ?? ""
        // Default-false / nil so older Stage 1 payloads still decode.
        physicianEdited = try c.decodeIfPresent(Bool.self, forKey: .physicianEdited) ?? false
        originalText = try c.decodeIfPresent(String.self, forKey: .originalText)
    }
}

/// Wire response from POST /notes/{id}/export-audit. The endpoint is
/// no-bytes; iOS uses the returned `sessionState` to know that the
/// server flipped to EXPORTED.
struct ExportAuditResponse: Codable, Sendable {
    let sessionId: String
    let sessionState: String
    let auditWritten: Bool

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case sessionState = "session_state"
        case auditWritten = "audit_written"
    }
}


/// Wire enum for the conflict resolution endpoint. Mirrors the backend
/// `ConflictResolutionRequest.action` literal; any new action must be
/// added here AND in `note_gen.service.resolve_conflict`.
enum ConflictResolutionAction: String, Sendable {
    case acceptVisual = "accept_visual"
    case rejectVisual = "reject_visual"
    case edit
}


/// Snapshot of an async Stage 2 job. iOS polls this on the dashboard to
/// know whether a session is still processing, ready for final review,
/// or stuck on a vision failure.
struct Stage2StatusResponse: Codable, Sendable, Equatable {
    let sessionId: String
    let jobId: String?
    /// One of "no_job", "pending", "running", "completed", "failed".
    let status: String
    let startedAt: String?
    let completedAt: String?
    let newNoteVersion: Int?
    let framesProcessed: Int
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case status
        case sessionId = "session_id"
        case jobId = "job_id"
        case startedAt = "started_at"
        case completedAt = "completed_at"
        case newNoteVersion = "new_note_version"
        case framesProcessed = "frames_processed"
        case errorMessage = "error_message"
    }

    /// Convenience flags for UI dispatch. Anything outside the known set
    /// (e.g. an older client + newer backend) collapses to "in progress"
    /// so the UI never silently drops a Stage 2 in flight.
    var isCompleted: Bool { status == "completed" }
    var isFailed: Bool { status == "failed" }
    var isRunning: Bool { status == "running" }
    var isInProgress: Bool { status == "pending" || status == "running" }
    var hasStarted: Bool { status != "no_job" }

    /// Collapses the five backend status strings onto the four visual
    /// states any Stage 2 surface (dashboard tile, review banner) needs
    /// to render. Lives next to the data so every UI site shares the
    /// same mapping.
    var displayKind: Stage2DisplayKind {
        guard hasStarted else { return .pending }
        if isCompleted { return .completed }
        if isFailed { return .failed }
        if isRunning { return .running }
        return .pending
    }
}

/// Four visual states a Stage 2 job collapses to. See
/// ``Stage2StatusResponse/displayKind``.
enum Stage2DisplayKind { case pending, running, completed, failed }


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

// MARK: - Transcription / Speaker Tagging

struct TranscriptSegmentResponse: Codable, Sendable {
    let id: String
    let startMs: Int
    let endMs: Int
    let text: String
    let speaker: String?
    let speakerConfidence: Float?
    let isVisualTrigger: Bool?
    let triggerType: String?

    enum CodingKeys: String, CodingKey {
        case id, text, speaker
        case startMs = "start_ms"
        case endMs = "end_ms"
        case speakerConfidence = "speaker_confidence"
        case isVisualTrigger = "is_visual_trigger"
        case triggerType = "trigger_type"
    }
}

struct TranscriptResponse: Codable, Sendable {
    let sessionId: String
    let providerUsed: String
    let segments: [TranscriptSegmentResponse]

    enum CodingKeys: String, CodingKey {
        case segments
        case sessionId = "session_id"
        case providerUsed = "provider_used"
    }
}

struct SpeakerTagRequest: Codable, Sendable {
    let segmentId: String
    let speaker: String
    let confidence: Float

    enum CodingKeys: String, CodingKey {
        case speaker, confidence
        case segmentId = "segment_id"
    }
}

struct SpeakerTagBatch: Codable, Sendable {
    let tags: [SpeakerTagRequest]
}

struct SpeakerTagApplyResponse: Codable, Sendable {
    let sessionId: String
    let segmentsUpdated: Int
    let segmentsUnknown: [String]

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case segmentsUpdated = "segments_updated"
        case segmentsUnknown = "segments_unknown"
    }
}

struct ScreenUploadResponse: Codable, Sendable {
    let sessionId: String
    let frameId: String
    let screenType: String
    let integrationStatus: String
    let noteSectionTarget: String?
    let claimsAdded: Int
    let newNoteVersion: Int?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case frameId = "frame_id"
        case screenType = "screen_type"
        case integrationStatus = "integration_status"
        case noteSectionTarget = "note_section_target"
        case claimsAdded = "claims_added"
        case newNoteVersion = "new_note_version"
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

/// Backend `/auth/me` shape — the canonical user identity after a
/// Cognito-issued JWT has been validated.
struct CurrentUserResponse: Codable, Sendable {
    let userId: String
    let email: String
    let fullName: String
    let roleRaw: String

    enum CodingKeys: String, CodingKey {
        case email
        case userId = "user_id"
        case fullName = "full_name"
        case roleRaw = "role"
    }

    /// Mapped role enum. Falls back to `.clinician` on any unrecognised
    /// value — keeps the iOS dispatch routing safe rather than 401-ing
    /// the user out of the app for a server-side rename.
    var role: UserRole { UserRole(rawValue: roleRaw) ?? .clinician }
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
