import Foundation
import Combine
import SwiftUI
import UIKit

/// Request payload for `SessionManager.startNewSession`. Defaults match the
/// backend's `POST /sessions` contract so call sites can omit anything
/// the physician hasn't customized.
struct SessionStartRequest {
    let specialty: String
    let consultationType: String?
    let encounterContext: String?
    let outputLanguage: String
    let encounterType: String
    let participants: [[String: Any]]?

    init(
        specialty: String,
        consultationType: String? = nil,
        encounterContext: String? = nil,
        outputLanguage: String = "en",
        encounterType: String = "doctor_patient",
        participants: [[String: Any]]? = nil
    ) {
        self.specialty = specialty
        self.consultationType = consultationType
        self.encounterContext = encounterContext
        self.outputLanguage = outputLanguage
        self.encounterType = encounterType
        self.participants = participants
    }
}

/// Manages the full session lifecycle -- bridges iOS UI to backend API.
@MainActor
final class SessionManager: ObservableObject {
    @Published var session: CaptureSession?
    @Published var note: NoteResponse?
    @Published var isProcessing = false
    @Published var processingStatus = ""
    @Published var showingReview = false
    @Published var showingPostEncounter = false
    @Published var error: String?

    /// On-device live captioner — runs alongside the canonical Whisper batch
    /// pipeline so the physician sees text accumulate during the encounter.
    /// Created lazily on first `startRecording`; the same instance is reused
    /// across pause/resume cycles within a session and discarded on stop.
    @Published var liveTranscriber: LiveTranscriber?

    private let api = APIClient.shared
    private var registry: CaptureSourceRegistry { .shared }
    private var audioSource: CaptureSource { registry.activeAudioSource }

    /// Language for live captions, captured from `SessionStartRequest` so we
    /// don't have to round-trip through AppState. Falls back to "en" if no
    /// session has been started.
    private var sessionLanguage: String = "en"

    // MARK: - Session Lifecycle

    func startNewSession(_ request: SessionStartRequest) async {
        error = nil
        do {
            let response = try await api.createSession(
                specialty: request.specialty,
                consultationType: request.consultationType,
                encounterContext: request.encounterContext,
                outputLanguage: request.outputLanguage,
                encounterType: request.encounterType,
                participants: request.participants
            )
            let captureSession = CaptureSession(id: response.id, specialty: request.specialty)
            captureSession.state = .consentPending
            session = captureSession
            sessionLanguage = request.outputLanguage
        } catch {
            self.error = "Failed to create session: \(error.localizedDescription)"
        }
    }

    func confirmConsent() async {
        guard let session else { return }
        do {
            _ = try await api.confirmConsent(sessionId: session.id)
            session.confirmConsent()
        } catch {
            self.error = "Consent failed: \(error.localizedDescription)"
        }
    }

    func startRecording() async {
        guard let session else { return }
        // Trigger iOS's camera + mic prompts on first run. Safe to call every
        // time — past `.notDetermined` it's a no-op and just refreshes the
        // cached status. Doing it here means the permission dialog fires
        // contextually, right after the physician confirms consent and hits
        // record, rather than at app launch where it'd feel out of place.
        await registry.builtIn.ensurePermissions()
        do {
            _ = try await api.startRecording(sessionId: session.id)
            session.startRecording()
            for source in registry.activeSourcesForSession {
                try source.start()
            }
            await startLiveTranscriber()
        } catch let sourceError as CaptureSourceError {
            self.error = sourceError.localizedDescription
        } catch {
            self.error = "Start failed: \(error.localizedDescription)"
        }
    }

    /// Spin up the on-device live captioner and bind it to the audio stream.
    /// Failure is silent — recording still proceeds with the canonical
    /// post-stop Whisper pipeline; live captions are UX sugar.
    private func startLiveTranscriber() async {
        let transcriber = liveTranscriber ?? LiveTranscriber()
        liveTranscriber = transcriber
        let language = sessionLanguage
        await transcriber.prepare(language: language)
        guard transcriber.isAvailable else { return }
        registry.builtIn.sampleBufferTap = { [weak transcriber] sampleBuffer in
            transcriber?.feed(sampleBuffer: sampleBuffer)
        }
        transcriber.start()
    }

    func pauseRecording() {
        // Pause local capture immediately for responsive UI; let the backend
        // state transition happen async so a slow network doesn't freeze the
        // recording lights. If the backend rejects the transition we surface
        // the error but keep the local pause — better to err on caution.
        for source in registry.activeSourcesForSession { source.pause() }
        liveTranscriber?.stop()
        session?.pause()
        Task {
            guard let session else { return }
            do {
                _ = try await api.pauseSession(sessionId: session.id)
            } catch {
                self.error = "Pause failed (backend): \(error.localizedDescription)"
            }
        }
    }

    func resumeRecording() {
        for source in registry.activeSourcesForSession { source.resume() }
        liveTranscriber?.start()
        session?.resume()
        Task {
            guard let session else { return }
            do {
                _ = try await api.resumeSession(sessionId: session.id)
            } catch {
                self.error = "Resume failed (backend): \(error.localizedDescription)"
            }
        }
    }

    func stopRecording() async {
        guard let session else { return }
        // Stop local capture FIRST so getRecordedAudioData has a complete buffer
        // by the time submitProcessing fires.
        for source in registry.activeSourcesForSession { source.stop() }
        // Tear down live captions — the canonical Whisper batch transcript
        // takes over from here. Interim text is intentionally discarded so
        // the UI doesn't show a stale preview alongside the final note.
        teardownLiveTranscriber()
        do {
            _ = try await api.stopRecording(sessionId: session.id)
            session.stopRecording()
            showingPostEncounter = true
            // Pipeline triggers from PostEncounterView after template confirmation.
        } catch {
            self.error = "Stop failed: \(error.localizedDescription)"
        }
    }

    /// Stop the live captioner and detach it from the audio stream. Safe to
    /// call when no captioner is active (no-op).
    private func teardownLiveTranscriber() {
        liveTranscriber?.stop()
        registry.builtIn.sampleBufferTap = nil
        liveTranscriber = nil
    }

    /// Triggered by PostEncounterView after template confirmation.
    func submitProcessing() async {
        showingPostEncounter = false
        await submitFrames()
        await submitAudio()
    }

    // MARK: - Frame Submission

    /// Mask each captured video frame and upload to the backend so the Stage 2
    /// vision pipeline can match them to transcript trigger segments. Frames
    /// are uploaded sequentially — the API is per-frame, not batched, so this
    /// is intentionally simple. Failures on individual frames are logged but
    /// don't abort the whole submission; a partial upload is better than none.
    private func submitFrames() async {
        guard let session, let videoSource = registry.activeVideoSource else { return }
        let frames = videoSource.capturedFrames
        guard !frames.isEmpty else { return }

        processingStatus = "Uploading frames…"
        var uploaded = 0
        for frame in frames {
            guard let image = UIImage(data: frame.imageData) else { continue }

            // Mask faces before any network egress. MaskingPipeline writes the
            // masking_confirmed audit event before returning, satisfying the
            // CLAUDE.md privacy guarantee.
            let result = await MaskingPipeline.shared.maskVideoFrame(image, sessionId: session.id)
            guard result.success, let maskedData = result.imageData else { continue }

            let timestampMs = Int((frame.timestamp * 1000).rounded())
            do {
                _ = try await api.uploadFrame(
                    sessionId: session.id,
                    jpegData: maskedData,
                    timestampMs: timestampMs
                )
                uploaded += 1
            } catch {
                // Per-frame failure is non-fatal — keep uploading the rest.
                continue
            }
        }
        processingStatus = "\(uploaded)/\(frames.count) frames uploaded"
    }

    // MARK: - Audio Submission

    private func submitAudio() async {
        guard let session else { return }
        guard let url = URL(string: "\(AppConfig.baseAPIPath)/transcription/\(session.id)") else {
            self.error = "Invalid API URL"
            return
        }
        isProcessing = true
        processingStatus = "Transcribing audio..."
        defer { isProcessing = false }

        let captured = audioSource.getRecordedAudioData()
        let audioPayload: Data
        let isDemoFallback: Bool
        if let captured, !captured.isEmpty {
            audioPayload = captured
            isDemoFallback = false
        } else {
            audioPayload = WAVBuilder.silence()
            isDemoFallback = true
        }

        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            let boundary = UUID().uuidString
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            if let token = KeychainHelper.shared.loadAuthToken() {
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }

            var body = Data()
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"audio_file\"; filename=\"recording.wav\"\r\n".utf8))
            body.append(Data("Content-Type: audio/wav\r\n\r\n".utf8))
            body.append(audioPayload)
            body.append(Data("\r\n--\(boundary)--\r\n".utf8))
            request.httpBody = body

            processingStatus = "Generating note..."
            let (_, response) = try await URLSession.shared.data(for: request)

            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw APIError.serverError((response as? HTTPURLResponse)?.statusCode ?? -1)
            }

            // Brief delay to let the backend persist Stage 1 before we GET it.
            try await Task.sleep(nanoseconds: 500_000_000)
            try await fetchNote()
            processingStatus = "Note ready for review"
        } catch {
            self.error = isDemoFallback
                ? "Simulator has no audio. Showing demo note."
                : "Transcription failed: \(error.localizedDescription)"
            note = createDemoNote(sessionId: session.id, specialty: session.specialty)
        }
    }

    private func fetchNote() async throws {
        guard let session else { return }
        note = try await api.getStage1Note(sessionId: session.id)
    }

    func approveNote() async {
        guard let session else { return }
        do {
            _ = try await api.approveFinalNote(sessionId: session.id)
            AurionHaptics.notification(.success)
        } catch {
            self.error = "Approval failed: \(error.localizedDescription)"
        }
    }

    /// Save the current session for later review without advancing the backend state.
    /// The session stays at AWAITING_REVIEW on the server. Clears local state so the
    /// physician can return to the dashboard and see the next patient.
    func saveForLater() {
        AurionHaptics.notification(.success)
        teardownLiveTranscriber()
        session?.clearPersistence()
        session = nil
        note = nil
        isProcessing = false
        showingReview = false
        showingPostEncounter = false
        processingStatus = ""
        error = nil
    }

    func endSession() {
        teardownLiveTranscriber()
        session?.clearPersistence()
        session = nil
        note = nil
        isProcessing = false
        showingReview = false
        showingPostEncounter = false
        processingStatus = ""
        error = nil
    }

    // MARK: - Crash Recovery

    func validateRecoveredSession(_ recoveredSession: CaptureSession) async -> Bool {
        do {
            let response = try await api.getSession(sessionId: recoveredSession.id)
            if let backendState = SessionState(rawValue: response.state) {
                if backendState.isActive {
                    recoveredSession.state = backendState
                    session = recoveredSession
                    return true
                } else {
                    SessionPersistence.clear()
                    return false
                }
            }
            return false
        } catch let error as APIError {
            switch error {
            case .notFound:
                SessionPersistence.clear()
                self.error = "Session expired. Starting fresh."
                return false
            case .offline:
                session = recoveredSession
                return true
            default:
                SessionPersistence.clear()
                return false
            }
        } catch {
            SessionPersistence.clear()
            return false
        }
    }

    // MARK: - Demo Fallback (Simulator with no mic input)

    private func createDemoNote(sessionId: String, specialty: String) -> NoteResponse {
        NoteResponse(
            sessionId: sessionId,
            stage: 1,
            version: 1,
            providerUsed: "demo",
            specialty: specialty,
            completenessScore: 0.83,
            sections: [
                NoteSectionResponse(id: "chief_complaint", title: "Chief Complaint", status: "populated", claims: [
                    NoteClaimResponse(id: "c1", text: "Physician noted patient presents with right knee pain for the past two weeks, worsening with activity.", sourceType: "transcript", sourceId: "seg_001", sourceQuote: "The patient presents with right knee pain for the past two weeks.")
                ]),
                NoteSectionResponse(id: "hpi", title: "History of Present Illness", status: "populated", claims: [
                    NoteClaimResponse(id: "c2", text: "Physician noted pain began gradually without specific injury, aggravated by stairs and prolonged standing.", sourceType: "transcript", sourceId: "seg_002", sourceQuote: "The pain began gradually without a specific injury.")
                ]),
                NoteSectionResponse(id: "physical_exam", title: "Physical Examination", status: "populated", claims: [
                    NoteClaimResponse(id: "c3", text: "Physician noted tenderness on palpation at the medial joint line of the right knee.", sourceType: "transcript", sourceId: "seg_003", sourceQuote: "There is tenderness on palpation at the medial joint line."),
                    NoteClaimResponse(id: "c4", text: "Physician noted range of motion restricted to approximately 110 degrees of flexion.", sourceType: "transcript", sourceId: "seg_004", sourceQuote: "Range of motion is restricted to approximately 110 degrees of flexion.")
                ]),
                NoteSectionResponse(id: "imaging_review", title: "Imaging Review", status: "pending_video", claims: []),
                NoteSectionResponse(id: "assessment", title: "Assessment", status: "populated", claims: [
                    NoteClaimResponse(id: "c5", text: "Physician stated working diagnosis of medial meniscus pathology, right knee.", sourceType: "transcript", sourceId: "seg_005", sourceQuote: "Working diagnosis is medial meniscus pathology.")
                ]),
                NoteSectionResponse(id: "plan", title: "Plan", status: "populated", claims: [
                    NoteClaimResponse(id: "c6", text: "Physician ordered MRI of the right knee and referred to physiotherapy for 6 weeks.", sourceType: "transcript", sourceId: "seg_006", sourceQuote: "We will order an MRI and start physiotherapy.")
                ]),
            ]
        )
    }
}
