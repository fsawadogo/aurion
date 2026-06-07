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
        captureMode: String = "multimodal",
        contextId: String? = nil
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
        // #316 (I2): the chosen saved context's server id. Non-PHI — an
        // opaque `ctx_<hex>` the backend maps to its pinned template. Omitted
        // for the free-text "Other" path so the server falls back to the
        // specialty-default template.
        if let contextId { body["context_id"] = contextId }
        return try await post(path: "/sessions", body: body)
    }

    func updateSessionTemplate(sessionId: String, specialty: String) async throws -> SessionResponse {
        return try await patch(path: "/sessions/\(sessionId)/template", body: ["specialty": specialty])
    }

    /// Set or clear the session's patient identifier (#61).
    ///
    /// Pass `identifier` to set; pass `nil` to clear. The server encrypts
    /// the value before storage; the audit row carries actor + cleared
    /// boolean but NEVER the identifier value itself.
    ///
    /// The identifier is PHI — never log it; the keyboard input view
    /// should opt out of QuickType suggestions and screen capture
    /// previews (see PatientIdentifierEditor).
    func setSessionIdentifier(sessionId: String, identifier: String?) async throws -> SessionResponse {
        // Backend's ExternalReferenceIdRequest treats null OR empty
        // string as "clear". We send empty string when the caller
        // wants to clear so the request body always serializes the
        // key (rather than relying on absent-key semantics, which
        // some HTTP middleware can drop).
        let body: [String: String] = [
            "external_reference_id": identifier ?? ""
        ]
        return try await patch(path: "/sessions/\(sessionId)/identifier", body: body)
    }

    /// Prior sessions for the same patient identifier (#61, full slice).
    ///
    /// Backend endpoint `GET /me/patients/{identifier}/sessions` returns
    /// the caller's owned sessions tagged with the same identifier,
    /// newest first. PHI scoping is enforced server-side: the response
    /// is empty for any other clinician's encounters even when their
    /// identifier matches.
    ///
    /// This is the single API call site for prior-encounters lookup —
    /// both `PriorEncountersRail` and `PriorEncountersListView` call
    /// here (DRY gate per AURION-CODING-WORKFLOW.md §6c).
    ///
    /// The identifier IS PHI — do NOT log it. The URL bakes it into the
    /// path, so anything that prints the URL is leaking; performRequest
    /// already redacts the path from error messages on this method
    /// because the generic error formatter never echoes the URL — see
    /// `validateResponse` for the contract.
    func listMySessionsByPatientIdentifier(_ identifier: String) async throws -> [PatientSessionMatch] {
        let escaped = identifier.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? identifier
        return try await get(path: "/me/patients/\(escaped)/sessions")
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

    // MARK: - Patient summary (#59)

    /// Latest patient summary for the session, or `nil` when none generated.
    /// Server returns null literally when none exists — we model that as
    /// optional rather than a 404 because a freshly-approved note legitimately
    /// has no summary yet.
    ///
    /// Important contract: this method ONLY returns nil when the backend
    /// emits literal `null` (no summary yet). Real failures (403 from
    /// non-CLINICIAN role, 5xx from upstream, network error, etc.) throw
    /// so the caller can distinguish "nothing to show" from "couldn't
    /// load." The previous `try?`-wrapped implementation conflated the
    /// two and made auth failures look like empty state.
    func getPatientSummary(sessionId: String) async throws -> PatientSummaryResponse? {
        return try await getOptional(
            path: "/me/notes/\(sessionId)/patient-summary"
        )
    }

    /// Generate a fresh patient summary. 409 when the note isn't approved
    /// yet (the caller should hide the action in that state); 502 on
    /// upstream LLM failure.
    func generatePatientSummary(sessionId: String) async throws -> PatientSummaryResponse {
        return try await post(path: "/me/notes/\(sessionId)/patient-summary")
    }

    /// Save physician edits to the summary text. Bumps the version on the
    /// server side; preserves the original provider attribution.
    func editPatientSummary(sessionId: String, body: String) async throws -> PatientSummaryResponse {
        return try await patch(
            path: "/me/notes/\(sessionId)/patient-summary",
            body: ["body": body]
        )
    }

    // MARK: - Orders (#58)

    /// List all order drafts for the session (newest first).
    /// Includes drafts + confirmed + cancelled rows; the UI sorts +
    /// filters as it sees fit.
    func listOrders(sessionId: String) async throws -> [NoteOrderResponse] {
        return try await get(path: "/me/notes/\(sessionId)/orders")
    }

    /// Run the LLM extractor against the latest approved note and
    /// persist each found order as a draft. 409 when the note isn't
    /// approved; 502 on upstream LLM failure. Returns the new drafts
    /// only (existing rows aren't included — the UI re-fetches to merge).
    func extractOrders(sessionId: String) async throws -> [NoteOrderResponse] {
        return try await post(path: "/me/notes/\(sessionId)/orders/extract")
    }

    /// Draft → confirmed. Idempotent on already-confirmed rows.
    /// Returns the updated row.
    func confirmOrder(sessionId: String, orderId: String) async throws -> NoteOrderResponse {
        return try await post(
            path: "/me/notes/\(sessionId)/orders/\(orderId)/confirm"
        )
    }

    /// Cancel an order. Soft delete — the row stays for audit; status
    /// flips to "cancelled". Refused on sent rows (the EMR owns them).
    func cancelOrder(sessionId: String, orderId: String) async throws -> NoteOrderResponse {
        return try await delete(
            path: "/me/notes/\(sessionId)/orders/\(orderId)"
        )
    }

    // MARK: - Coding suggestions (#69)

    /// List all coding suggestions for the session (newest first).
    /// Includes suggested + edited + confirmed + rejected rows.
    func listCodingSuggestions(sessionId: String) async throws -> [CodingSuggestionResponse] {
        return try await get(path: "/me/notes/\(sessionId)/coding-suggestions")
    }

    /// Run the LLM coding extractor against the latest approved note.
    /// 409 when not approved; 502 on upstream LLM failure.
    func extractCodingSuggestions(sessionId: String) async throws -> [CodingSuggestionResponse] {
        return try await post(path: "/me/notes/\(sessionId)/coding-suggestions/extract")
    }

    /// Suggested / edited → confirmed.
    func confirmCodingSuggestion(sessionId: String, suggestionId: String) async throws -> CodingSuggestionResponse {
        return try await post(
            path: "/me/notes/\(sessionId)/coding-suggestions/\(suggestionId)/confirm"
        )
    }

    /// Reject a suggestion. Row stays for audit; not eligible for EMR
    /// write-back.
    func rejectCodingSuggestion(sessionId: String, suggestionId: String) async throws -> CodingSuggestionResponse {
        return try await post(
            path: "/me/notes/\(sessionId)/coding-suggestions/\(suggestionId)/reject"
        )
    }

    /// Override code and/or description. Status flips to "edited".
    /// Re-runs catalog validation; physician-typed bogus codes still
    /// get flagged.
    func editCodingSuggestion(
        sessionId: String,
        suggestionId: String,
        code: String,
        description: String
    ) async throws -> CodingSuggestionResponse {
        return try await patch(
            path: "/me/notes/\(sessionId)/coding-suggestions/\(suggestionId)",
            body: ["code": code, "description": description]
        )
    }

    // MARK: - EMR write-back (#57)

    /// Connector catalog — drives the picker. In pilot deployments
    /// `available == ["stub"]` and the card surfaces a "Pilot mode"
    /// banner so the physician doesn't think the note actually went
    /// to a chart system. Real connectors (FHIR / Oscar / Epic SMART)
    /// register through env config on the backend.
    func listEmrConnectors() async throws -> EmrConnectorsResponse {
        return try await get(path: "/me/emr/connectors")
    }

    /// All write-back attempts for the session, newest first.
    func listEmrWriteBacks(sessionId: String) async throws -> [EmrWriteBackResponse] {
        return try await get(path: "/me/notes/\(sessionId)/emr")
    }

    /// Kick off a write-back. Connector errors (network blip, EMR
    /// auth, etc.) land as `status=failed` rows in the response,
    /// NOT as HTTP errors — the audit trail captures every attempt.
    /// 409 surfaces only when the note isn't approved; 400 only when
    /// the connector key is unknown.
    func sendEmrWriteBack(sessionId: String, connector: String?) async throws -> EmrWriteBackResponse {
        return try await post(
            path: "/me/notes/\(sessionId)/emr/send",
            body: ["connector": connector ?? NSNull()]
        )
    }

    // MARK: - Live preview (#64)

    /// Generate a fresh draft preview from the partial transcript text.
    /// Runs on a separate code path from canonical Stage 1 — a hung
    /// preview never blocks recording-stop. 502 on upstream LLM failure;
    /// 409 when the session has no specialty assigned.
    func generateLivePreview(
        sessionId: String,
        partialTranscript: String,
        outputLanguage: String = "en"
    ) async throws -> LivePreviewResponse {
        return try await post(
            path: "/me/sessions/\(sessionId)/preview",
            body: [
                "partial_transcript": partialTranscript,
                "output_language": outputLanguage,
            ]
        )
    }

    /// Latest preview snapshot for the session, or nil when none yet.
    /// Same contract as getPatientSummary: nil ONLY for the literal-null
    /// "no preview yet" response; real failures throw.
    func getLatestLivePreview(sessionId: String) async throws -> LivePreviewResponse? {
        return try await getOptional(
            path: "/me/sessions/\(sessionId)/preview"
        )
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

    // MARK: - Clips (P1-5 dual-mode visual evidence)

    /// Upload a single MASKED clip MP4 to the backend so the Stage 2
    /// vision pipeline can route it to the configured clip-capable
    /// provider (Gemini native; OpenAI/Anthropic via midpoint-still
    /// fallback). Backend persists at `clips/{session_id}/{clip_id}.mp4`
    /// with KMS encryption + 24h TTL post-Stage-2.
    ///
    /// Streams the multi-MB file via `URLSession.uploadTask(with:fromFile:)`
    /// so the body never sits in RAM — the multipart envelope (boundary
    /// header + form fields + file content + closing boundary) is
    /// staged to a single temp file before the upload starts and
    /// cleaned up after the upload completes. `Data(contentsOf:)` would
    /// pull the full clip into memory and is explicitly NOT used.
    ///
    /// P0-01 fail-closed contract: callers MUST only call this after
    /// `MaskingPipeline.maskClip` returned `.success`. `masking_confirmed`
    /// is hardcoded `true` because the masking step has already
    /// completed by the time we reach here.
    ///
    /// P0-02 masking-proof contract: same `frame_type` / counts shape as
    /// `uploadFrame`, but with clip-specific counts (frames_total,
    /// frames_with_faces). The backend rejects uploads missing these
    /// fields.
    @discardableResult
    func uploadClip(
        sessionId: String,
        clipFileURL: URL,
        timestampMs: Int,
        durationMs: Int,
        triggerSegmentId: String,
        framesTotal: Int,
        framesWithFaces: Int
    ) async throws -> ClipUploadResponse {
        let prepared = try Self.prepareClipUpload(
            baseURL: baseURL,
            sessionId: sessionId,
            clipFileURL: clipFileURL,
            timestampMs: timestampMs,
            durationMs: durationMs,
            triggerSegmentId: triggerSegmentId,
            framesTotal: framesTotal,
            framesWithFaces: framesWithFaces,
            authToken: KeychainHelper.shared.bearerToken()
        )
        // Belt and suspenders: ensure the body temp file is removed
        // regardless of how this method exits.
        defer { try? FileManager.default.removeItem(at: prepared.bodyFileURL) }

        let (data, response) = try await uploadFileWithRequest(
            request: prepared.request,
            bodyFileURL: prepared.bodyFileURL
        )
        try validateResponse(response, data: data)
        return try JSONDecoder().decode(ClipUploadResponse.self, from: data)
    }

    /// Pure builder for the uploadClip request + staged body file. Pulled
    /// out so tests can verify the multipart envelope without observing
    /// it through URLSession (the upload-from-file path doesn't expose
    /// the body via `URLRequest.httpBodyStream` at the URLProtocol layer
    /// — URLSession reads it directly off disk).
    ///
    /// Returns the URLRequest with method/auth/timeout/content-type set
    /// and the on-disk body file URL. The caller is responsible for
    /// removing `bodyFileURL` after the upload completes.
    static func prepareClipUpload(
        baseURL: String,
        sessionId: String,
        clipFileURL: URL,
        timestampMs: Int,
        durationMs: Int,
        triggerSegmentId: String,
        framesTotal: Int,
        framesWithFaces: Int,
        authToken: String?
    ) throws -> (request: URLRequest, bodyFileURL: URL) {
        let url = URL(string: "\(baseURL)/clips/\(sessionId)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        // The upload-from-file path needs longer than the standard 30s
        // for large clips — 7s @ 720p is typically ~7-15 MB. 60s gives
        // us a comfortable margin for the LTE worst case without blowing
        // past Stage 2's overall budget.
        request.timeoutInterval = 60
        if let authToken {
            request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue(
            "multipart/form-data; boundary=\(boundary)",
            forHTTPHeaderField: "Content-Type"
        )

        // Build the multipart envelope. Same primitives `uploadFrame`
        // uses (MultipartBuilder + the headerForFile / closingBoundaryData
        // accessors) so frame and clip can't drift on field ordering or
        // boundary format.
        var builder = MultipartBuilder(boundary: boundary)
        builder.appendField("timestamp_ms", "\(timestampMs)")
        builder.appendField("duration_ms", "\(durationMs)")
        builder.appendField("trigger_segment_id", triggerSegmentId)
        builder.appendField("frames_total", "\(framesTotal)")
        builder.appendField("frames_with_faces", "\(framesWithFaces)")
        builder.appendField("masking_confirmed", "true")

        var prefix = builder.bodySoFar
        prefix.append(builder.headerForFile(name: "clip", filename: "clip.mp4", mime: "video/mp4"))
        let suffix = builder.closingBoundaryData()
        let bodyFileURL = try buildMultipartBodyFile(
            prefix: prefix,
            fileURL: clipFileURL,
            suffix: suffix
        )
        return (request, bodyFileURL)
    }

    /// `URLSession.upload(for:fromFile:)` wrapper that classifies errors
    /// the same way `performRequest(_:)` does. The split exists because
    /// `uploadTask(with:fromFile:)` doesn't go through `data(for:)` —
    /// it's a different URLSession code path and we want one place that
    /// turns URLError codes into APIError cases.
    private func uploadFileWithRequest(
        request: URLRequest,
        bodyFileURL: URL
    ) async throws -> (Data, URLResponse) {
        do {
            return try await URLSession.shared.upload(for: request, fromFile: bodyFileURL)
        } catch let error as URLError {
            switch error.code {
            case .notConnectedToInternet, .networkConnectionLost,
                 .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
                throw APIError.offline
            case .timedOut:
                throw APIError.timeout
            default:
                throw APIError.networkError(error.localizedDescription)
            }
        }
    }

    /// Stage the multipart envelope to a single temp file so the upload
    /// can stream from disk. Layout: `prefix` (boundary + form fields +
    /// file part header) → raw bytes of `fileURL` → `suffix` (closing
    /// boundary). Returns the URL of the staged body file; caller owns
    /// cleanup. `static` because it touches no instance state — easier
    /// to unit-test in isolation.
    static func buildMultipartBodyFile(prefix: Data, fileURL: URL, suffix: Data) throws -> URL {
        let bodyURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-clip-upload-\(UUID().uuidString).bin")
        try? FileManager.default.removeItem(at: bodyURL)
        FileManager.default.createFile(atPath: bodyURL.path, contents: nil, attributes: nil)

        let handle = try FileHandle(forWritingTo: bodyURL)
        defer { try? handle.close() }
        try handle.write(contentsOf: prefix)

        // Stream the source file in 64KB chunks so even multi-MB clips
        // never need a full in-memory copy. Matches the dual-mode plan's
        // privacy budget — raw clip bytes (already masked at this point)
        // pass through the iOS process without inflating the resident set.
        let reader = try FileHandle(forReadingFrom: fileURL)
        defer { try? reader.close() }
        while true {
            let chunk = reader.readData(ofLength: 64 * 1024)
            if chunk.isEmpty { break }
            try handle.write(contentsOf: chunk)
        }
        try handle.write(contentsOf: suffix)
        return bodyURL
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

    /// GET that accepts a literal JSON `null` body as `nil` instead
    /// of as a decode error. Real HTTP failures (4xx / 5xx) still
    /// throw via `validateResponse` — so callers can distinguish
    /// "no resource yet" from "couldn't reach the resource."
    ///
    /// Used by the GET-latest paths for resources that may legitimately
    /// not exist yet (patient summary, live preview).
    private func getOptional<T: Decodable>(path: String) async throws -> T? {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        addAuth(&request)
        let (data, response) = try await performRequest(request)
        try validateResponse(response, data: data)
        // Treat literal `null` (4 bytes) as nil — avoids a decode
        // error when the backend signals "no resource yet" via the
        // JSON null sentinel.
        let trimmed = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == "null" { return nil }
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

    /// HTTP DELETE that decodes a JSON response body. Backend uses DELETE
    /// for soft-delete-with-return endpoints (e.g. /orders/{id} flipping
    /// the row to status=cancelled and returning the updated row), so
    /// the helper expects a typed response shape.
    private func delete<T: Decodable>(path: String, body: [String: Any]? = nil) async throws -> T {
        try await mutate(method: "DELETE", path: path, body: body)
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
        body.append(headerForFile(name: name, filename: filename, mime: mime))
        body.append(data)
        body.append(Self.crlf)
    }

    /// Multipart header bytes that introduce a file part — boundary,
    /// content-disposition, content-type, blank line. Exposed publicly
    /// so the streamed-from-file upload path (uploadClip) can write the
    /// header to a temp body file, then stream raw file bytes, then
    /// append the closing boundary — without buffering the file
    /// contents in memory. The in-memory path (`appendFile`) wraps
    /// this same helper to keep the byte layout identical.
    func headerForFile(name: String, filename: String, mime: String) -> Data {
        var data = Data()
        data.append("--\(boundary)\r\n".data(using: .utf8)!)
        data.append(
            "Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n"
                .data(using: .utf8)!
        )
        data.append("Content-Type: \(mime)\r\n\r\n".data(using: .utf8)!)
        return data
    }

    /// Closing boundary bytes — the trailing CRLF after the file
    /// content followed by `--boundary--\r\n`. Exposed for the same
    /// reason as `headerForFile`.
    func closingBoundaryData() -> Data {
        var data = Data()
        data.append(Self.crlf)
        data.append("--\(boundary)--\r\n".data(using: .utf8)!)
        return data
    }

    /// In-memory body wrapped in the closing boundary. Used by the
    /// non-streaming upload paths (uploadFrame, uploadScreenFrame).
    func finish() -> Data {
        var final = body
        final.append("--\(boundary)--\r\n".data(using: .utf8)!)
        return final
    }

    /// Read-only snapshot of the body bytes accumulated so far —
    /// boundary + all appended fields and files BEFORE the closing
    /// boundary is written. Used by streamed-from-file upload paths
    /// that need the prefix (form fields) without the closing
    /// boundary.
    var bodySoFar: Data { body }
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

/// Per-session provider routing overrides (P1-7). Mirrors the backend's
/// `ProviderOverridesSchema` — all fields optional, decode is permissive
/// (unknown keys ignored, missing keys treated as nil) so a future
/// override key lands without breaking deployed iOS builds.
///
/// `visualEvidenceMode` is the load-bearing field today: when set, the
/// iOS dispatcher in `SessionManager.extractEvidence` uses it instead
/// of the AppConfig pipeline default. The string survives as raw so
/// `VisualEvidenceMode(rawValue:)` decides whether it's parseable; an
/// unparseable string falls back to the global default with a log
/// warning rather than crashing.
struct ProviderOverrides: Codable, Sendable, Equatable {
    let transcription: String?
    let noteGeneration: String?
    let vision: String?
    let visionClip: String?
    let visualEvidenceMode: String?

    enum CodingKeys: String, CodingKey {
        case transcription
        case noteGeneration = "note_generation"
        case vision
        case visionClip = "vision_clip"
        case visualEvidenceMode = "visual_evidence_mode"
    }

    init(
        transcription: String? = nil,
        noteGeneration: String? = nil,
        vision: String? = nil,
        visionClip: String? = nil,
        visualEvidenceMode: String? = nil
    ) {
        self.transcription = transcription
        self.noteGeneration = noteGeneration
        self.vision = vision
        self.visionClip = visionClip
        self.visualEvidenceMode = visualEvidenceMode
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        transcription = try c.decodeIfPresent(String.self, forKey: .transcription)
        noteGeneration = try c.decodeIfPresent(String.self, forKey: .noteGeneration)
        vision = try c.decodeIfPresent(String.self, forKey: .vision)
        visionClip = try c.decodeIfPresent(String.self, forKey: .visionClip)
        visualEvidenceMode = try c.decodeIfPresent(String.self, forKey: .visualEvidenceMode)
    }
}

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
    /// Patient identifier (#61) — opaque string the clinic uses to tie this
    /// session to a chart in their EMR. NULL when the physician hasn't set
    /// one yet. Server decrypts before serialization for the owning
    /// clinician + admins; absent in the response for other roles.
    let externalReferenceId: String?
    /// Per-session provider routing overrides (P1-7). NULL when no
    /// overrides were set at creation. Read by `SessionManager.extractEvidence`
    /// to drive Stage 2 dual-mode routing without a second backend call.
    let providerOverrides: ProviderOverrides?
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, specialty, state
        case clinicianId = "clinician_id"
        case encounterType = "encounter_type"
        case captureMode = "capture_mode"
        case externalReferenceId = "external_reference_id"
        case providerOverrides = "provider_overrides"
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
        externalReferenceId = try c.decodeIfPresent(String.self, forKey: .externalReferenceId)
        providerOverrides = try c.decodeIfPresent(ProviderOverrides.self, forKey: .providerOverrides)
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
        externalReferenceId: String? = nil,
        providerOverrides: ProviderOverrides? = nil,
        createdAt: String,
        updatedAt: String
    ) {
        self.id = id
        self.clinicianId = clinicianId
        self.specialty = specialty
        self.state = state
        self.encounterType = encounterType
        self.captureMode = captureMode
        self.externalReferenceId = externalReferenceId
        self.providerOverrides = providerOverrides
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }
}

/// Slim, count-only summary of the prior-encounter context Stage 1
/// note-gen consumed for this note (#61, full slice).
///
/// Mirrors the backend `PriorContextUsedSummary` Pydantic type
/// (`backend/app/core/types.py`). Carries NO PHI:
///   * ``encountersReferenced`` is the integer count of prior visits
///     the LLM actually saw — drives the badge's
///     ``encounters_referenced > 0`` visibility gate.
///   * ``lastEncounterDate`` is the ISO-8601 calendar date of the
///     most recent prior visit, or nil when no prior was found.
///
/// Decoded from ``prior_context_used`` on the note response payload.
/// Older payloads (pre-#61 backends) decode unchanged because the
/// field is optional all the way down.
struct PriorContextUsed: Codable, Sendable, Equatable {
    let encountersReferenced: Int
    let lastEncounterDate: String?

    enum CodingKeys: String, CodingKey {
        case encountersReferenced = "encounters_referenced"
        case lastEncounterDate = "last_encounter_date"
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
    /// #61 full slice — populated when Stage 1 actually consumed
    /// prior encounters into the LLM prompt. nil for cold-start
    /// sessions (no identifier set) and for older backend payloads
    /// pre-#61. Read by ``NoteReviewView`` to gate the
    /// "Context-aware" badge: visible iff
    /// ``priorContextUsed?.encountersReferenced > 0``.
    let priorContextUsed: PriorContextUsed?

    enum CodingKeys: String, CodingKey {
        case stage, version, specialty, sections
        case sessionId = "session_id"
        case providerUsed = "provider_used"
        case completenessScore = "completeness_score"
        case priorContextUsed = "prior_context_used"
    }

    init(
        sessionId: String,
        stage: Int,
        version: Int,
        providerUsed: String,
        specialty: String,
        completenessScore: Double,
        sections: [NoteSectionResponse],
        priorContextUsed: PriorContextUsed? = nil
    ) {
        self.sessionId = sessionId
        self.stage = stage
        self.version = version
        self.providerUsed = providerUsed
        self.specialty = specialty
        self.completenessScore = completenessScore
        self.sections = sections
        self.priorContextUsed = priorContextUsed
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionId = try c.decode(String.self, forKey: .sessionId)
        stage = try c.decode(Int.self, forKey: .stage)
        version = try c.decode(Int.self, forKey: .version)
        providerUsed = try c.decode(String.self, forKey: .providerUsed)
        specialty = try c.decode(String.self, forKey: .specialty)
        completenessScore = try c.decode(Double.self, forKey: .completenessScore)
        sections = try c.decode([NoteSectionResponse].self, forKey: .sections)
        // Optional + back-compatible: older Stage 1 payloads (pre-#61)
        // simply lack the key, and `decodeIfPresent` returns nil
        // without throwing. The badge stays hidden in that case.
        priorContextUsed = try c.decodeIfPresent(
            PriorContextUsed.self, forKey: .priorContextUsed
        )
    }
}

struct NoteSectionResponse: Codable, Equatable, Sendable {
    let id: String
    let title: String
    let status: String
    let claims: [NoteClaimResponse]
}

/// Visual evidence kind backing a `NoteClaimResponse`. Mirrors the
/// backend `FrameCaption.evidence_kind` field (see
/// `backend/app/core/types.py`). Frame-kind claims are the historical
/// default — when the field is absent on the wire (older payloads,
/// transcript-only claims) we decode as `.frame` so every existing
/// fixture stays valid (P1-1's "additive, byte-identical" contract).
///
/// Only `visual` sourceType claims should ever carry `.clip`; transcript
/// and screen claims have no clip backing by construction. The chip
/// renderer guards on `sourceType == "visual"` before showing the
/// play-triangle indicator so a stray `.clip` value on a non-visual
/// claim doesn't mis-render.
enum EvidenceKind: String, Codable, Sendable, Equatable {
    case frame
    case clip
}

struct NoteClaimResponse: Codable, Equatable, Sendable {
    let id: String
    let text: String
    let sourceType: String
    let sourceId: String
    let sourceQuote: String
    let physicianEdited: Bool
    let originalText: String?
    /// Dual-mode visual evidence (P1-1 ↔ P1-6). `.frame` for the
    /// historical path + every transcript/screen claim. `.clip` only
    /// when the backing artifact is a video clip the reviewer can play
    /// inline. Defaults to `.frame` so legacy payloads decode unchanged.
    let evidenceKind: EvidenceKind
    /// Encoded clip window length in milliseconds; nil for frames.
    /// Surfaced in the `FullClipView` toolbar as a duration pill.
    let durationMs: Int?
    /// Local file URL or backend-signed remote URL of the masked clip
    /// for playback. nil until the note endpoint plumbs the citation
    /// `clip_url` through to the wire — see P1-6 plan "Out of scope".
    /// The chip indicator surfaces regardless; the viewer guards on this.
    let clipURL: URL?

    init(
        id: String,
        text: String,
        sourceType: String,
        sourceId: String,
        sourceQuote: String,
        physicianEdited: Bool = false,
        originalText: String? = nil,
        evidenceKind: EvidenceKind = .frame,
        durationMs: Int? = nil,
        clipURL: URL? = nil
    ) {
        self.id = id
        self.text = text
        self.sourceType = sourceType
        self.sourceId = sourceId
        self.sourceQuote = sourceQuote
        self.physicianEdited = physicianEdited
        self.originalText = originalText
        self.evidenceKind = evidenceKind
        self.durationMs = durationMs
        self.clipURL = clipURL
    }

    enum CodingKeys: String, CodingKey {
        case id, text
        case sourceType = "source_type"
        case sourceId = "source_id"
        case sourceQuote = "source_quote"
        case physicianEdited = "physician_edited"
        case originalText = "original_text"
        case evidenceKind = "evidence_kind"
        case durationMs = "duration_ms"
        case clipURL = "clip_url"
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
        // Default to `.frame` so older payloads (no `evidence_kind`
        // field) decode unchanged — backend contract for P1-1 was
        // additive on existing rows.
        evidenceKind = try c.decodeIfPresent(EvidenceKind.self, forKey: .evidenceKind) ?? .frame
        durationMs = try c.decodeIfPresent(Int.self, forKey: .durationMs)
        clipURL = try c.decodeIfPresent(URL.self, forKey: .clipURL)
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

/// Structured order draft extracted from an approved note (#58).
///
/// Per-kind details shape (server-enforced; we trust the field):
///   imaging      → { modality, body_part, laterality, indication }
///   lab          → { panel, indication }
///   referral     → { specialty, reason, urgency }
///   prescription → { drug, dose, frequency, duration, indication }
///
/// The `details` JSON object is decoded as `[String: AnyCodableString]`
/// since the values are always strings server-side; we trade a small
/// type-erasure cost for not having to model every per-kind shape.
///
/// `drugValidated` (#58 follow-up via #172): three-state catalog check
/// for prescription rows only. True = recognized; False = checked and
/// not in catalog (UI surfaces verify-before-prescribing warning);
/// null = non-prescription kind OR legacy row.
struct NoteOrderResponse: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let sessionId: String
    let kind: String  // imaging / lab / referral / prescription
    let details: [String: String]
    let status: String  // draft / confirmed / sent / cancelled
    let sourceClaimIds: [String]
    let drugValidated: Bool?
    let catalogVersion: String?
    let physicianConfirmedAt: String?
    let sentAt: String?
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, kind, details, status
        case sessionId = "session_id"
        case sourceClaimIds = "source_claim_ids"
        case drugValidated = "drug_validated"
        case catalogVersion = "catalog_version"
        case physicianConfirmedAt = "physician_confirmed_at"
        case sentAt = "sent_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        sessionId = try c.decode(String.self, forKey: .sessionId)
        kind = try c.decode(String.self, forKey: .kind)
        status = try c.decode(String.self, forKey: .status)
        // details values come back as JSON strings; decode each as a
        // String for a stable iOS-side type. Server contract is
        // string-only per the system prompt + parser in
        // modules/orders/service.py.
        if let raw = try? c.decode([String: String].self, forKey: .details) {
            details = raw
        } else if let any = try? c.decode([String: AnyCodableValue].self, forKey: .details) {
            details = any.mapValues { $0.stringValue }
        } else {
            details = [:]
        }
        sourceClaimIds = try c.decodeIfPresent([String].self, forKey: .sourceClaimIds) ?? []
        drugValidated = try c.decodeIfPresent(Bool.self, forKey: .drugValidated)
        catalogVersion = try c.decodeIfPresent(String.self, forKey: .catalogVersion)
        physicianConfirmedAt = try c.decodeIfPresent(String.self, forKey: .physicianConfirmedAt)
        sentAt = try c.decodeIfPresent(String.self, forKey: .sentAt)
        createdAt = try c.decode(String.self, forKey: .createdAt)
        updatedAt = try c.decode(String.self, forKey: .updatedAt)
    }
}

/// Live preview snapshot (#64) — draft note generated mid-encounter
/// from the partial transcript. NOT the canonical Stage 1 note:
///   * `stage` is always 0, `isDraft` always true — any consumer
///     that treats this as a chartable note has a bug
///   * lives in its own table server-side (live_note_previews); the
///     canonical Stage 1 pipeline at recording-stop ignores all
///     preview rows
struct LivePreviewResponse: Codable, Sendable, Equatable {
    let id: String
    let sessionId: String
    let version: Int
    let stage: Int  // always 0
    let isDraft: Bool  // always true
    let sections: [LivePreviewSectionPayload]
    let transcriptChars: Int
    let completenessScore: Double
    let providerUsed: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, version, stage, sections
        case sessionId = "session_id"
        case isDraft = "is_draft"
        case transcriptChars = "transcript_chars"
        case completenessScore = "completeness_score"
        case providerUsed = "provider_used"
        case createdAt = "created_at"
    }
}

/// One section in a live preview. Shape mirrors the canonical
/// NoteSection — but the `claims[].sourceId` values are synthetic
/// (`preview_seg_0`) since real transcript anchors don't exist
/// during recording yet. Downstream consumers MUST NOT treat preview
/// `sourceId` values as canonical anchors.
struct LivePreviewSectionPayload: Codable, Sendable, Equatable {
    let id: String
    let title: String?
    let status: String  // populated / not_captured / pending_video / processing_failed
    let claims: [LivePreviewClaimPayload]
}

struct LivePreviewClaimPayload: Codable, Sendable, Equatable {
    let id: String
    let text: String
    let sourceType: String
    let sourceId: String

    enum CodingKeys: String, CodingKey {
        case id, text
        case sourceType = "source_type"
        case sourceId = "source_id"
    }
}

/// Connector catalog response (#57). The pilot deployment registers
/// only the `stub` connector by default; real backends opt in via
/// env vars (see AURION_EMR_FHIR_ENDPOINT in #173).
struct EmrConnectorsResponse: Codable, Sendable, Equatable {
    let available: [String]
    let `default`: String
}

/// EMR write-back attempt (#57). Three-state semantics paired with
/// `status`:
///   * `scheduledAt == nil` + `status == "sent"` → succeeded
///   * `scheduledAt == nil` + `status == "failed"` → terminal (no
///     more retries budgeted)
///   * `scheduledAt != nil` + `status == "failed"` → auto-retry
///     queued (the backend's retry scheduler / worker will drain
///     it; the UI surfaces "Will retry at HH:MM")
struct EmrWriteBackResponse: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let sessionId: String
    let connector: String
    let status: String  // queued / sending / sent / failed
    let externalId: String?
    let payloadFingerprint: String
    let errorReason: String?
    let attemptCount: Int
    let sentAt: String?
    let scheduledAt: String?
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, connector, status
        case sessionId = "session_id"
        case externalId = "external_id"
        case payloadFingerprint = "payload_fingerprint"
        case errorReason = "error_reason"
        case attemptCount = "attempt_count"
        case sentAt = "sent_at"
        case scheduledAt = "scheduled_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

/// E/M / ICD-10 / CPT coding suggestion (#69).
///
/// Strategic separate-surface inference. The clinical note stays
/// descriptive-only by policy; this row carries the inferential
/// mapping from claims to billing codes on its own surface, marked
/// "assistive — physician must confirm."
///
/// `codeValidated` (#69 follow-up via #171): three-state catalog
/// check. True = in our curated catalog; False = checked and not in
/// catalog (UI surfaces verify-before-billing warning); null = legacy
/// row from before validation.
struct CodingSuggestionResponse: Codable, Sendable, Equatable, Identifiable {
    let id: String
    let sessionId: String
    let codeSystem: String  // em / icd10 / cpt
    let code: String
    let description: String
    let justification: String
    let sourceClaimIds: [String]
    let confidence: String  // low / medium / high
    let status: String  // suggested / confirmed / rejected / edited
    let codeValidated: Bool?
    let catalogVersion: String?
    let physicianActionAt: String?
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, code, description, justification, confidence, status
        case sessionId = "session_id"
        case codeSystem = "code_system"
        case sourceClaimIds = "source_claim_ids"
        case codeValidated = "code_validated"
        case catalogVersion = "catalog_version"
        case physicianActionAt = "physician_action_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

/// Permissive decoder for heterogeneous JSON values that we want to
/// project down to String for storage. Used by NoteOrderResponse when
/// the server emits e.g. a numeric urgency or null laterality.
enum AnyCodableValue: Codable, Sendable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode(Int.self) { self = .int(v); return }
        if let v = try? c.decode(Double.self) { self = .double(v); return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        self = .null
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    var stringValue: String {
        switch self {
        case .string(let v): return v
        case .int(let v): return String(v)
        case .double(let v): return String(v)
        case .bool(let v): return v ? "true" : "false"
        case .null: return ""
        }
    }
}

/// Patient-facing after-visit summary (#59).
///
/// Lives on its own table on the server; one row per session, with
/// version bumped on each regenerate / physician edit. The body is the
/// Grade-8 plain-language summary the LLM produced — never the clinical
/// note. `generatedByProvider` is the provider tag at *original*
/// generation; physician edits preserve this so the audit story stays
/// attributable.
struct PatientSummaryResponse: Codable, Sendable, Equatable {
    let id: String
    let sessionId: String
    let version: Int
    let body: String
    let generatedByProvider: String
    let physicianEdited: Bool
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, version, body
        case sessionId = "session_id"
        case generatedByProvider = "generated_by_provider"
        case physicianEdited = "physician_edited"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

/// One match from `GET /me/patients/{identifier}/sessions` (#61, full slice).
///
/// Mirror of the FastAPI `PatientSessionMatch` model in
/// `backend/app/api/v1/me.py` and the TS type in `web/types/index.ts`.
/// Slim on purpose — the consumer (`PriorEncountersRail` /
/// `PriorEncountersListView`) only needs enough to render a date +
/// specialty + state pill and route on tap, so we resolve the rest of
/// the session lazily by id if the user opens it.
///
/// Backend already excludes other clinicians' sessions; iOS additionally
/// filters out PURGED rows + the current session id at the consumer
/// layer (matches the dashboard recent-strip rule shipped earlier).
struct PatientSessionMatch: Codable, Sendable, Equatable, Identifiable {
    let sessionId: String
    let specialty: String
    let state: String
    let createdAt: String

    /// Identifiable via session id so SwiftUI lists / ForEach iterate
    /// stably across reloads.
    var id: String { sessionId }

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case specialty
        case state
        case createdAt = "created_at"
    }
}

struct AlliedHealthMember: Codable, Sendable, Equatable, Identifiable {
    /// Local-only identifier so SwiftUI `ForEach` / `.onDelete` can
    /// iterate stably even when two rows share the same name (e.g. two
    /// scribes named "Sam" on a busy clinic day). Synthesized on decode
    /// and on the `init(name:role:email:)` convenience init below; never
    /// serialized to the backend (the JSON column shape stays
    /// `[{name, role, email?}]`).
    let id: UUID
    let name: String
    let role: String
    /// Optional contact email. Backend persists the team list as a
    /// `list[dict]` JSON column, so an extra key round-trips
    /// transparently — pre-existing rows decode with `email = nil` and
    /// stay forward-compatible.
    let email: String?

    enum CodingKeys: String, CodingKey {
        case name, role, email
    }

    init(id: UUID = UUID(), name: String, role: String, email: String? = nil) {
        self.id = id
        self.name = name
        self.role = role
        self.email = email
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.id = UUID()
        self.name = try c.decode(String.self, forKey: .name)
        self.role = try c.decode(String.self, forKey: .role)
        self.email = try c.decodeIfPresent(String.self, forKey: .email)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name)
        try c.encode(role, forKey: .role)
        try c.encodeIfPresent(email, forKey: .email)
    }
}

/// One clinician-authored context under a visit type (#313 B1 / #315 I1).
///
/// A "context" is a sub-mode of a visit type — e.g. under "new_patient",
/// contexts "LL" (lower limb) and "Breast" — each optionally pinned to a
/// built-in specialty template. `templateKey == nil` means "use the
/// physician's specialty default".
///
/// Wire shape: `{id, label, template_key, template_ref}`. The backend assigns
/// `id` (`ctx_<8 hex>`) for a context sent with an empty `id`; a well-formed id
/// round-trips so an edit updates in place. `templateRef` is ALWAYS null in
/// phase 1 (custom templates are #318) — it is neither sent nor surfaced.
struct VisitTypeContext: Codable, Sendable, Identifiable {
    /// Local-only stable identity for SwiftUI `ForEach`. Two freshly added
    /// contexts both carry `serverID == ""`, so the wire id can't drive
    /// `Identifiable` until the server has assigned one. Synthesized on
    /// decode and on the memberwise init; never serialized.
    let localID: UUID
    /// Server-assigned id. Empty string for a context the clinician just
    /// added and hasn't saved yet; preserved verbatim on edit.
    var serverID: String
    var label: String
    /// One of the 8 built-in template keys (``BuiltInTemplate/keys``), or nil
    /// = use the physician's specialty default.
    var templateKey: String?

    var id: UUID { localID }

    enum CodingKeys: String, CodingKey {
        case serverID = "id"
        case label
        case templateKey = "template_key"
    }

    init(serverID: String = "", label: String, templateKey: String? = nil) {
        self.localID = UUID()
        self.serverID = serverID
        self.label = label
        self.templateKey = templateKey
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.localID = UUID()
        self.serverID = (try? c.decode(String.self, forKey: .serverID)) ?? ""
        self.label = try c.decode(String.self, forKey: .label)
        self.templateKey = try c.decodeIfPresent(String.self, forKey: .templateKey)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(serverID, forKey: .serverID)
        try c.encode(label, forKey: .label)
        try c.encodeIfPresent(templateKey, forKey: .templateKey)
    }

    /// Serialize to the `[String: Any]` shape `updateProfile` expects. An
    /// empty `id` signals "new" to the backend; a non-empty id is preserved.
    /// `template_key` is omitted when nil (the backend defaults it to null =
    /// specialty default); `template_ref` is never sent (always null phase 1).
    static func encodePayload(_ ctx: VisitTypeContext) -> [String: Any] {
        var dict: [String: Any] = [
            "id": ctx.serverID,
            "label": ctx.label,
        ]
        if let tk = ctx.templateKey {
            dict["template_key"] = tk
        }
        return dict
    }
}

struct PhysicianProfileResponse: Codable, Sendable {
    let clinicianId: String
    let displayName: String
    let practiceType: String?
    let primarySpecialty: String
    let preferredTemplates: [String]
    let consultationTypes: [String]
    /// Visit-type key → ordered contexts (#313 B1 / #315 I1). Decoded with a
    /// `[:]` default so a backend on an older schema doesn't break the fetch.
    let contextsPerVisitType: [String: [VisitTypeContext]]
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
        case contextsPerVisitType = "contexts_per_visit_type"
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
        contextsPerVisitType = (try? c.decode(
            [String: [VisitTypeContext]].self, forKey: .contextsPerVisitType
        )) ?? [:]
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

/// Backend `POST /clips/{session_id}` shape. Mirrors `FrameUploadResponse`
/// with clip-specific echoes. Extra fields are decoded leniently so the
/// iOS client survives a backend that adds new metadata.
struct ClipUploadResponse: Codable, Sendable {
    let sessionId: String
    let clipId: String?
    let s3Key: String
    let bytesUploaded: Int
    let durationMs: Int?
    let framesTotal: Int?
    let framesWithFaces: Int?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case clipId = "clip_id"
        case s3Key = "s3_key"
        case bytesUploaded = "bytes_uploaded"
        case durationMs = "duration_ms"
        case framesTotal = "frames_total"
        case framesWithFaces = "frames_with_faces"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionId = try c.decode(String.self, forKey: .sessionId)
        clipId = try c.decodeIfPresent(String.self, forKey: .clipId)
        s3Key = try c.decode(String.self, forKey: .s3Key)
        bytesUploaded = try c.decode(Int.self, forKey: .bytesUploaded)
        durationMs = try c.decodeIfPresent(Int.self, forKey: .durationMs)
        framesTotal = try c.decodeIfPresent(Int.self, forKey: .framesTotal)
        framesWithFaces = try c.decodeIfPresent(Int.self, forKey: .framesWithFaces)
    }

    init(
        sessionId: String,
        clipId: String? = nil,
        s3Key: String,
        bytesUploaded: Int,
        durationMs: Int? = nil,
        framesTotal: Int? = nil,
        framesWithFaces: Int? = nil
    ) {
        self.sessionId = sessionId
        self.clipId = clipId
        self.s3Key = s3Key
        self.bytesUploaded = bytesUploaded
        self.durationMs = durationMs
        self.framesTotal = framesTotal
        self.framesWithFaces = framesWithFaces
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

/// Visual evidence routing mode. Mirrors the backend's
/// `VisualEvidenceMode` enum (dual-mode plan, AppConfig schema). The
/// iOS dispatcher in `SessionManager.extractEvidence(for:)` switches
/// on this once.
///
/// - `framesOnly` (default — Phase 1 zero-risk): every trigger emits a
///   still frame, byte-identical to today's behavior.
/// - `clipsOnly`: every trigger emits a 7s video clip via the ring
///   buffer.
/// - `hybrid`: per-trigger routing keyed on `clipTriggerKinds`
///   containment.
enum VisualEvidenceMode: String, Codable, Sendable, Equatable {
    case framesOnly = "frames_only"
    case clipsOnly = "clips_only"
    case hybrid
}

struct ClientPipelineResponse: Codable, Sendable {
    let stage1SkipWindowSeconds: Int
    let frameWindowClinicMs: Int
    let frameWindowProceduralMs: Int
    let screenCaptureFps: Int
    let videoCaptureFps: Int
    /// Dual-mode visual evidence routing. Defaults to `.framesOnly` so
    /// a backend that hasn't been upgraded yet preserves byte-identical
    /// behavior on the iOS side.
    let visualEvidenceMode: VisualEvidenceMode
    /// Clip extraction window in milliseconds (centered on the trigger
    /// timestamp). Used by `extractEvidence` when in `.clipsOnly` /
    /// `.hybrid` mode. Defaults to the dual-mode plan's documented 7000 ms.
    let clipWindowMs: Int
    /// Trigger kinds that route to a clip in `.hybrid` mode. Defaults
    /// mirror the master plan ("motion", "rom", "gait", "procedural").
    let clipTriggerKinds: [String]

    enum CodingKeys: String, CodingKey {
        case stage1SkipWindowSeconds = "stage1_skip_window_seconds"
        case frameWindowClinicMs = "frame_window_clinic_ms"
        case frameWindowProceduralMs = "frame_window_procedural_ms"
        case screenCaptureFps = "screen_capture_fps"
        case videoCaptureFps = "video_capture_fps"
        case visualEvidenceMode = "visual_evidence_mode"
        case clipWindowMs = "clip_window_ms"
        case clipTriggerKinds = "clip_trigger_kinds"
    }

    init(
        stage1SkipWindowSeconds: Int,
        frameWindowClinicMs: Int,
        frameWindowProceduralMs: Int,
        screenCaptureFps: Int,
        videoCaptureFps: Int,
        visualEvidenceMode: VisualEvidenceMode = .framesOnly,
        clipWindowMs: Int = 7_000,
        clipTriggerKinds: [String] = ["motion", "rom", "gait", "procedural"]
    ) {
        self.stage1SkipWindowSeconds = stage1SkipWindowSeconds
        self.frameWindowClinicMs = frameWindowClinicMs
        self.frameWindowProceduralMs = frameWindowProceduralMs
        self.screenCaptureFps = screenCaptureFps
        self.videoCaptureFps = videoCaptureFps
        self.visualEvidenceMode = visualEvidenceMode
        self.clipWindowMs = clipWindowMs
        self.clipTriggerKinds = clipTriggerKinds
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stage1SkipWindowSeconds = try c.decode(Int.self, forKey: .stage1SkipWindowSeconds)
        frameWindowClinicMs = try c.decode(Int.self, forKey: .frameWindowClinicMs)
        frameWindowProceduralMs = try c.decode(Int.self, forKey: .frameWindowProceduralMs)
        screenCaptureFps = try c.decode(Int.self, forKey: .screenCaptureFps)
        videoCaptureFps = try c.decode(Int.self, forKey: .videoCaptureFps)
        // Optional with safe defaults — keeps the iOS client forward-
        // compatible with older backends that haven't yet emitted the
        // dual-mode keys via GET /config.
        visualEvidenceMode = try c.decodeIfPresent(VisualEvidenceMode.self, forKey: .visualEvidenceMode) ?? .framesOnly
        clipWindowMs = try c.decodeIfPresent(Int.self, forKey: .clipWindowMs) ?? 7_000
        clipTriggerKinds = try c.decodeIfPresent([String].self, forKey: .clipTriggerKinds) ?? ["motion", "rom", "gait", "procedural"]
    }
}

struct ClientFeatureFlagsResponse: Codable, Sendable {
    let screenCaptureEnabled: Bool
    let noteVersioningEnabled: Bool
    let sessionPauseResumeEnabled: Bool
    let perSessionProviderOverride: Bool
    let metaWearablesEnabled: Bool
    // ── Post-pilot card visibility (lane-full/card-visibility-flags) ──────
    // Four downstream-of-Stage-1 cards on the note-review screen — hidden
    // by default for everyone; ADMIN flips per-card via the web portal.
    // SessionNoteView gates each card's render on the corresponding flag,
    // and because the flag check happens at the parent level the card's
    // own `.onAppear` fetch is never triggered when hidden.
    //
    // Decoded with `decodeIfPresent` (see the custom init below) so the
    // iOS client stays forward-compatible with older backends that haven't
    // yet emitted these keys via GET /config — they fall back to `false`
    // (hide the card) which is the safe default.
    let ordersCardEnabled: Bool
    let codingCardEnabled: Bool
    let patientSummaryCardEnabled: Bool
    let emrWritebackCardEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case screenCaptureEnabled = "screen_capture_enabled"
        case noteVersioningEnabled = "note_versioning_enabled"
        case sessionPauseResumeEnabled = "session_pause_resume_enabled"
        case perSessionProviderOverride = "per_session_provider_override"
        case metaWearablesEnabled = "meta_wearables_enabled"
        case ordersCardEnabled = "orders_card_enabled"
        case codingCardEnabled = "coding_card_enabled"
        case patientSummaryCardEnabled = "patient_summary_card_enabled"
        case emrWritebackCardEnabled = "emr_writeback_card_enabled"
    }

    // Memberwise init so RemoteConfig's `@Published` default can build
    // a snapshot without going through the decoder.
    init(
        screenCaptureEnabled: Bool,
        noteVersioningEnabled: Bool,
        sessionPauseResumeEnabled: Bool,
        perSessionProviderOverride: Bool,
        metaWearablesEnabled: Bool,
        ordersCardEnabled: Bool,
        codingCardEnabled: Bool,
        patientSummaryCardEnabled: Bool,
        emrWritebackCardEnabled: Bool
    ) {
        self.screenCaptureEnabled = screenCaptureEnabled
        self.noteVersioningEnabled = noteVersioningEnabled
        self.sessionPauseResumeEnabled = sessionPauseResumeEnabled
        self.perSessionProviderOverride = perSessionProviderOverride
        self.metaWearablesEnabled = metaWearablesEnabled
        self.ordersCardEnabled = ordersCardEnabled
        self.codingCardEnabled = codingCardEnabled
        self.patientSummaryCardEnabled = patientSummaryCardEnabled
        self.emrWritebackCardEnabled = emrWritebackCardEnabled
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        screenCaptureEnabled = try c.decode(Bool.self, forKey: .screenCaptureEnabled)
        noteVersioningEnabled = try c.decode(Bool.self, forKey: .noteVersioningEnabled)
        sessionPauseResumeEnabled = try c.decode(Bool.self, forKey: .sessionPauseResumeEnabled)
        perSessionProviderOverride = try c.decode(Bool.self, forKey: .perSessionProviderOverride)
        metaWearablesEnabled = try c.decode(Bool.self, forKey: .metaWearablesEnabled)
        // Card-visibility flags — `decodeIfPresent` keeps iOS forward-
        // compatible with older backends. Hidden-by-default is the safe
        // fallback (the cards are post-pilot scaffolding).
        ordersCardEnabled = try c.decodeIfPresent(Bool.self, forKey: .ordersCardEnabled) ?? false
        codingCardEnabled = try c.decodeIfPresent(Bool.self, forKey: .codingCardEnabled) ?? false
        patientSummaryCardEnabled = try c.decodeIfPresent(Bool.self, forKey: .patientSummaryCardEnabled) ?? false
        emrWritebackCardEnabled = try c.decodeIfPresent(Bool.self, forKey: .emrWritebackCardEnabled) ?? false
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
