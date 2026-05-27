import Foundation
import Combine
import SwiftUI
import UIKit

/// Stage 1 SLA (CLAUDE.md §"MVP Success Criteria"): record-stop → note
/// delivered within 30 s. The UI surfaces every phase so the clinician
/// knows whether to wait, retry, or fall back to dictation.
enum Stage1Status: Equatable {
    case idle
    case uploading
    case generating
    case ready
    case timedOut(elapsed: TimeInterval)
    case failed(reason: String)

    /// When non-nil, ProcessingView shows a retry prompt with this copy.
    var retryPrompt: (title: String, detail: String)? {
        switch self {
        case .timedOut(let elapsed):
            return ("Stage 1 timed out", "The note didn't generate within \(Int(elapsed))s.")
        case .failed(let reason):
            return ("Stage 1 failed", reason)
        case .idle, .uploading, .generating, .ready:
            return nil
        }
    }
}

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
    let captureMode: CaptureMode

    init(
        specialty: String,
        consultationType: String? = nil,
        encounterContext: String? = nil,
        outputLanguage: String = "en",
        encounterType: String = "doctor_patient",
        participants: [[String: Any]]? = nil,
        captureMode: CaptureMode = .multimodal
    ) {
        self.specialty = specialty
        self.consultationType = consultationType
        self.encounterContext = encounterContext
        self.outputLanguage = outputLanguage
        self.encounterType = encounterType
        self.participants = participants
        self.captureMode = captureMode
    }
}

/// A frame that failed on-device masking, tagged with its origin so the
/// retry path knows which endpoint to re-fire (video → `/frames`, screen →
/// `/screen`). Conflating them silently routed screen retries to the video
/// endpoint.
struct FailedMaskingFrame: Identifiable {
    enum Kind { case video, screen }
    let frame: CapturedFrame
    let kind: Kind
    var id: UUID { frame.id }
}

/// Manages the full session lifecycle -- bridges iOS UI to backend API.
@MainActor
final class SessionManager: ObservableObject {
    @Published var session: CaptureSession?
    @Published var note: NoteResponse?
    @Published private(set) var uiState: SessionUIState = .idle
    @Published var processingStatus = ""
    @Published var error: String?
    @Published var stage1Status: Stage1Status = .idle
    /// Wall-clock when the capture pipeline last began streaming. Used by
    /// the CaptureView's stop button to enforce the minimum recording
    /// duration so the audio delegate has time to deliver its first
    /// buffer (warm-up is typically ~500ms but can exceed 1s on cold
    /// AVAudioSession activation). Reset on stop.
    @Published private(set) var recordingStartedAt: Date?

    /// Frames whose on-device masking failed during `submitFrames` /
    /// `submitScreenFrames`. Per CLAUDE.md the pipeline is fail-closed: these
    /// frames were NOT uploaded. Surfaced to the clinician so they can choose
    /// to retry or skip; cleared when retrying or when the session is torn
    /// down. Each entry carries a `kind` so the retry path dispatches to the
    /// correct upload endpoint.
    @Published var maskingFailedFrames: [FailedMaskingFrame] = []

    /// On-device live captioner — runs alongside the canonical Whisper batch
    /// pipeline so the physician sees text accumulate during the encounter.
    /// Created lazily on first `startRecording`; the same instance is reused
    /// across pause/resume cycles within a session and discarded on stop.
    @Published var liveTranscriber: LiveTranscriber?

    /// Screen capture co-runs with audio/video in multimodal mode when the
    /// feature flag is on. ReplayKit lifecycle is independent of the
    /// AVCaptureSession sources, so it lives outside the registry. `let`,
    /// not `@Published` — ScreenCaptureManager is itself an ObservableObject;
    /// views subscribe to it directly.
    let screenCapture = ScreenCaptureManager()

    /// Drives the lock-screen + Dynamic Island Live Activity for the
    /// in-flight session. Fail-soft: if Live Activities are disabled,
    /// the coordinator is a no-op and capture continues normally.
    private let liveActivity = LiveActivityCoordinator()

    private let api = APIClient.shared
    private var registry: CaptureSourceRegistry { .shared }
    private var audioSource: CaptureSource { registry.activeAudioSource }

    /// Screen capture eligibility — combines the mode's intent with the
    /// runtime feature flag. Pure mode capability lives on `CaptureMode`.
    func wantsScreenCapture(for mode: CaptureMode) -> Bool {
        mode.includesScreen && RemoteConfig.shared.featureFlags.screenCaptureEnabled
    }

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
                participants: request.participants,
                captureMode: request.captureMode.rawValue
            )
            let participants: [SessionParticipant] = (request.participants ?? []).compactMap { dict in
                guard let name = dict["name"] as? String,
                      let role = dict["role"] as? String else { return nil }
                return SessionParticipant(name: name, role: role)
            }
            let captureSession = CaptureSession(
                id: response.id,
                specialty: request.specialty,
                captureMode: request.captureMode,
                encounterType: request.encounterType,
                participants: participants
            )
            captureSession.state = .consentPending
            session = captureSession
            sessionLanguage = request.outputLanguage
        } catch {
            self.error = "Failed to create session: \(error.localizedDescription)"
        }
    }

    func confirmConsent(method: ConsentMethod) async {
        guard let session else { return }
        do {
            _ = try await api.confirmConsent(sessionId: session.id, method: method)
            session.confirmConsent(method: method)
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
            try await coldStartCapturePipeline(for: session.captureMode)
            // Lock-screen + Dynamic Island Live Activity. Fires after
            // the backend transition succeeded — no point starting an
            // activity for a session the server rejected.
            liveActivity.start(sessionID: session.id, specialty: session.specialty)
            // Stamp the local clock so the stop button can require a
            // minimum recording duration. AVAudioSession + AVCaptureSession
            // need ~500ms–2s to deliver the first sample buffer; stopping
            // before that gives us a zero-byte audioPCMData and "No audio
            // captured" later in submitAudio.
            recordingStartedAt = Date()
        } catch let sourceError as CaptureSourceError {
            self.error = sourceError.localizedDescription
        } catch {
            self.error = "Start failed: \(error.localizedDescription)"
        }
    }

    /// Earliest moment the user is allowed to tap Stop. The stop button is
    /// disabled until ``recordingElapsed`` reaches this threshold so the
    /// capture pipeline has a chance to deliver buffers — see startRecording.
    nonisolated static let minimumRecordingSeconds: TimeInterval = 2

    /// Wall-clock seconds since the capture pipeline started, or nil if
    /// we haven't kicked off yet. Re-evaluated by SwiftUI on every TimelineView
    /// tick so the stop button enables automatically once the floor is hit.
    func recordingElapsed(at now: Date = Date()) -> TimeInterval? {
        guard let recordingStartedAt else { return nil }
        return now.timeIntervalSince(recordingStartedAt)
    }

    /// True once recording has run long enough that stopping should
    /// produce a non-empty audio buffer. UI gates the Stop button on this.
    func stopAllowed(at now: Date = Date()) -> Bool {
        guard let elapsed = recordingElapsed(at: now) else { return false }
        return elapsed >= Self.minimumRecordingSeconds
    }

    /// Capture sources to run for the active session, filtered by mode.
    /// Video-capable sources are dropped in audio-only modes; identity is
    /// compared via `===` because the registry holds the same instances.
    private var activeSourcesForCurrentMode: [CaptureSource] {
        guard let session, !session.captureMode.includesVideo else {
            return registry.activeSourcesForSession
        }
        return registry.activeSourcesForSession.filter { source in
            source === registry.activeAudioSource
        }
    }

    /// Shared cold-start sequence: align builtIn's video flag with the mode,
    /// start every selected source, attach live captions, kick off screen
    /// capture when eligible. Used by `startRecording`, `adoptSession`, and
    /// the offline branch of `validateRecoveredSession`.
    private func coldStartCapturePipeline(for mode: CaptureMode) async throws {
        registry.builtIn.includeVideo = mode.includesVideo
        for source in activeSourcesForCurrentMode {
            try source.start()
        }
        await startLiveTranscriber()
        if wantsScreenCapture(for: mode) {
            screenCapture.startCapture()
        }
    }

    private func stopScreenCaptureIfRunning() {
        if screenCapture.isRecording { screenCapture.stopCapture() }
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
        for source in activeSourcesForCurrentMode { source.pause() }
        liveActivity.setPaused(true)
        // ReplayKit has no real pause. ScreenCaptureManager.startCapture
        // wipes capturedScreenFrames on resume, so pre-pause frames are
        // currently lost — M-12 (audited purge lifecycle) will decide
        // whether to preserve them across pauses.
        stopScreenCaptureIfRunning()
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
        for source in activeSourcesForCurrentMode { source.resume() }
        liveActivity.setPaused(false)
        if let session, wantsScreenCapture(for: session.captureMode) {
            screenCapture.startCapture()
        }
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
        // Clear the start timestamp so a future Resume → Stop pair re-arms
        // the minimum-duration guard from scratch.
        recordingStartedAt = nil
        // Stop local capture FIRST so getRecordedAudioData has a complete buffer
        // by the time submitProcessing fires.
        for source in activeSourcesForCurrentMode { source.stop() }
        stopScreenCaptureIfRunning()
        // Drop the Live Activity now (not after Stage 1) — the lock-
        // screen pill is a "still recording" affordance; once capture
        // stops, the activity is misleading. Re-entry happens via the
        // Sessions inbox.
        liveActivity.end()
        // Tear down live captions — the canonical Whisper batch transcript
        // takes over from here. Interim text is intentionally discarded so
        // the UI doesn't show a stale preview alongside the final note.
        teardownLiveTranscriber()
        do {
            _ = try await api.stopRecording(sessionId: session.id)
            session.stopRecording()
            uiState = .postEncounter
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
        uiState = .processing
        await submitFrames()
        await submitAudio()
        // Screen frames merge into the note AFTER Stage 1 generated it,
        // so this runs last. The screen pipeline is fully on-device for
        // PHI; the upload carries the masking proof from P0-02.
        await submitScreenFrames()
    }

    // MARK: - Frame Submission

    /// Mask each captured video frame and upload to the backend so the Stage 2
    /// vision pipeline can match them to transcript trigger segments. Frames
    /// are uploaded sequentially — the API is per-frame, not batched, so this
    /// is intentionally simple.
    ///
    /// Frames whose masking fails are NEVER uploaded (P0-01 fail-closed) and
    /// are kept in `maskingFailedFrames` so the clinician can retry or skip.
    /// Network upload failures on a successfully-masked frame are non-fatal —
    /// we keep uploading the rest.
    private func submitFrames() async {
        guard let session, let videoSource = registry.activeVideoSource else { return }
        let frames = videoSource.capturedFrames
        guard !frames.isEmpty else { return }

        processingStatus = "Uploading frames…"
        // Clear only video-kind failures from a prior attempt — screen
        // failures (if any) belong to a separate retry path.
        maskingFailedFrames.removeAll { $0.kind == .video }
        var uploaded = 0
        var maskingFailed = 0
        for frame in frames {
            guard let image = UIImage(data: frame.imageData) else {
                // Cannot decode the captured bytes — treat as a masking failure
                // so the audit trail and UI both reflect it.
                maskingFailed += 1
                maskingFailedFrames.append(FailedMaskingFrame(frame: frame, kind: .video))
                continue
            }

            // Mask faces before any network egress. MaskingPipeline writes the
            // masking_confirmed audit event on success and masking_failed on
            // any failure path; a failed result MUST NOT be uploaded.
            let result = await MaskingPipeline.shared.maskVideoFrame(image, sessionId: session.id)
            guard result.success, let maskedData = result.imageData else {
                maskingFailed += 1
                maskingFailedFrames.append(FailedMaskingFrame(frame: frame, kind: .video))
                continue
            }

            let timestampMs = Int((frame.timestamp * 1000).rounded())
            do {
                _ = try await api.uploadFrame(
                    sessionId: session.id,
                    jpegData: maskedData,
                    timestampMs: timestampMs,
                    frameType: result.frameType.rawValue,
                    facesDetected: result.facesDetected,
                    phiRegionsRedacted: result.phiRegionsRedacted
                )
                uploaded += 1
            } catch {
                // Per-frame network failure is non-fatal — keep uploading the
                // rest. Distinct from masking failure: the frame WAS masked.
                continue
            }
        }
        if maskingFailed > 0 {
            processingStatus = "\(uploaded)/\(frames.count) uploaded · \(maskingFailed) failed masking"
        } else {
            processingStatus = "\(uploaded)/\(frames.count) frames uploaded"
        }
    }

    /// Re-run masking + upload for any frames that previously failed masking.
    /// Called when the clinician chooses "Retry" on the masking-failure prompt.
    /// Dispatches by `kind` so video → `/frames` and screen → `/screen` —
    /// uploading a screen frame to the wrong endpoint would let unredacted
    /// PHI through to S3.
    func retryFailedMaskingFrames() async {
        guard let session, !maskingFailedFrames.isEmpty else { return }
        let toRetry = maskingFailedFrames
        maskingFailedFrames = []
        AuditLogger.log(
            event: .maskingFailureRetried,
            sessionId: session.id,
            extra: ["frame_count": "\(toRetry.count)"]
        )

        processingStatus = "Retrying masking on \(toRetry.count) frame(s)…"
        var uploaded = 0
        var stillFailed = 0
        for failed in toRetry {
            guard let image = UIImage(data: failed.frame.imageData) else {
                stillFailed += 1
                maskingFailedFrames.append(failed)
                continue
            }
            let timestampMs = Int((failed.frame.timestamp * 1000).rounded())
            let masked: MaskingResult
            switch failed.kind {
            case .video:
                masked = await MaskingPipeline.shared.maskVideoFrame(image, sessionId: session.id)
            case .screen:
                masked = await MaskingPipeline.shared.redactScreenCapture(image, sessionId: session.id)
            }
            guard masked.success, let maskedData = masked.imageData else {
                stillFailed += 1
                maskingFailedFrames.append(failed)
                continue
            }
            do {
                switch failed.kind {
                case .video:
                    _ = try await api.uploadFrame(
                        sessionId: session.id,
                        jpegData: maskedData,
                        timestampMs: timestampMs,
                        frameType: masked.frameType.rawValue,
                        facesDetected: masked.facesDetected,
                        phiRegionsRedacted: masked.phiRegionsRedacted
                    )
                case .screen:
                    _ = try await api.uploadScreenFrame(
                        sessionId: session.id,
                        jpegData: maskedData,
                        timestampMs: timestampMs,
                        phiRegionsRedacted: masked.phiRegionsRedacted
                    )
                }
                uploaded += 1
            } catch {
                continue
            }
        }
        if stillFailed > 0 {
            processingStatus = "Retried: \(uploaded) uploaded · \(stillFailed) still failed"
        } else {
            processingStatus = "Retried: \(uploaded) frame(s) uploaded"
        }
    }

    // MARK: - Screen Frame Submission

    /// Mask + upload each captured screen frame. Failed masking quarantines
    /// into `maskingFailedFrames` as `.screen`-kind entries so the retry path
    /// re-fires the correct endpoint. The backend processes each frame
    /// through OCR and merges the resulting lab values / imaging metadata
    /// into the note as screen-sourced claims.
    ///
    /// The "Note ready" status from `submitAudio` is preserved when no
    /// screen frames were captured or no claims were added — appending
    /// "· N screens" rather than overwriting.
    private func submitScreenFrames() async {
        guard let session else { return }
        let frames = screenCapture.capturedScreenFrames
        guard !frames.isEmpty else { return }

        // Clear only screen-kind failures from a prior run.
        maskingFailedFrames.removeAll { $0.kind == .screen }
        let priorStatus = processingStatus
        var uploaded = 0
        var integratedClaims = 0
        var maskingFailed = 0
        for frame in frames {
            guard let image = UIImage(data: frame.imageData) else {
                maskingFailed += 1
                maskingFailedFrames.append(FailedMaskingFrame(frame: frame, kind: .screen))
                continue
            }
            let result = await MaskingPipeline.shared.redactScreenCapture(image, sessionId: session.id)
            guard result.success, let redactedData = result.imageData else {
                maskingFailed += 1
                maskingFailedFrames.append(FailedMaskingFrame(frame: frame, kind: .screen))
                continue
            }
            let timestampMs = Int((frame.timestamp * 1000).rounded())
            do {
                let response = try await api.uploadScreenFrame(
                    sessionId: session.id,
                    jpegData: redactedData,
                    timestampMs: timestampMs,
                    phiRegionsRedacted: result.phiRegionsRedacted
                )
                uploaded += 1
                integratedClaims += response.claimsAdded
            } catch {
                // Per-frame network failure is non-fatal — keep uploading.
                continue
            }
        }
        if integratedClaims > 0 {
            // Merged claims write a new note version on the backend —
            // refresh so the review UI shows the updated sections.
            try? await fetchNote()
            processingStatus = "\(priorStatus) · \(integratedClaims) screen claim\(integratedClaims == 1 ? "" : "s") added"
        } else if uploaded > 0 {
            processingStatus = "\(priorStatus) · \(uploaded) screens (no extractable data)"
        }
    }

    /// Discard frames whose masking failed without uploading them. The frames
    /// remain absent from Stage 2 visual enrichment — Stage 2 will surface
    /// reduced coverage in the completeness score.
    func skipFailedMaskingFrames() {
        guard let session, !maskingFailedFrames.isEmpty else { return }
        let skipped = maskingFailedFrames.count
        maskingFailedFrames = []
        AuditLogger.log(
            event: .maskingFailureSkipped,
            sessionId: session.id,
            extra: ["frame_count": "\(skipped)"]
        )
        processingStatus = "Skipped \(skipped) unmasked frame(s)"
    }

    // MARK: - Audio Submission

    private func submitAudio() async {
        guard let session else { return }
        guard let url = URL(string: "\(AppConfig.baseAPIPath)/transcription/\(session.id)") else {
            self.error = "Invalid API URL"
            return
        }
        uiState = .processing

        let captured = audioSource.getRecordedAudioData()
        let audioPayload: Data
        let isDemoFallback: Bool
        if let captured, !captured.isEmpty {
            audioPayload = captured
            isDemoFallback = false
        } else if DemoMode.isEnabled {
            // Simulator dev path — substitute silence so the pipeline runs
            // end-to-end without a microphone. NEVER reachable in pilot or
            // production builds (P0-03).
            audioPayload = WAVBuilder.silence()
            isDemoFallback = true
        } else {
            // Empty audioPCMData means the AVAudioSession delegate never
            // delivered a buffer. In practice this is almost always a
            // too-short recording — the stop-button guard below the start
            // timestamp should catch most of these, but on first-launch
            // mic warmup or a backgrounded session it's still possible.
            // Phrasing avoids implying the mic / system is broken.
            self.error = "Recording was too short. Speak for at least a few seconds before stopping."
            stage1Status = .failed(reason: "Recording too short")
            // Stay on ProcessingView so the retry prompt is reachable.
            return
        }

        stage1Status = .uploading
        processingStatus = "Uploading audio…"
        let stage1Start = Date()

        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            // True wall-clock SLA cap. `request.timeoutInterval` is only
            // an inactivity timer (resets every byte), so a slow trickle
            // could blow past 30s. The resource timeout below is the
            // hard cap — set on a per-call configuration.
            request.timeoutInterval = AppConfig.stage1TimeoutSeconds
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = AppConfig.stage1TimeoutSeconds
            config.timeoutIntervalForResource = AppConfig.stage1TimeoutSeconds
            let session = URLSession(configuration: config)

            let boundary = UUID().uuidString
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            if let token = KeychainHelper.shared.loadAuthToken() {
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }

            var builder = MultipartBuilder(boundary: boundary)
            builder.appendFile("audio_file", filename: "recording.wav", mime: "audio/wav", data: audioPayload)
            request.httpBody = builder.finish()

            stage1Status = .generating
            processingStatus = "Generating note…"
            let (data, response) = try await session.data(for: request)

            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw APIError.serverError((response as? HTTPURLResponse)?.statusCode ?? -1)
            }

            // Speaker tagging is best-effort; the voice embedding stays in
            // Keychain. Failure here doesn't block note generation.
            if let transcript = try? JSONDecoder().decode(TranscriptResponse.self, from: data) {
                await applySpeakerTags(transcript: transcript)
            }

            try await Task.sleep(nanoseconds: 500_000_000)
            try await fetchNote()
            let elapsed = Date().timeIntervalSince(stage1Start)
            stage1Status = .ready
            processingStatus = "Note ready for review (\(Int(elapsed))s)"
            uiState = .noteReady
        } catch let urlError as URLError where urlError.code == .timedOut {
            recordStage1Timeout(sessionId: session.id, since: stage1Start)
        } catch APIError.timeout {
            // fetchNote() can also time out; surface as the same state so
            // the user sees retry, not a generic failure.
            recordStage1Timeout(sessionId: session.id, since: stage1Start)
        } catch {
            // P0-03: NEVER fabricate clinical content in production. The demo
            // fallback is `#if DEBUG`-stripped so the call site doesn't even
            // exist in pilot/release binaries — `createDemoNote` is not in
            // scope outside Debug builds.
            #if DEBUG
            if DemoMode.isEnabled {
                self.error = isDemoFallback
                    ? "Simulator has no audio. Showing demo note."
                    : "Transcription failed: \(error.localizedDescription)"
                stage1Status = .ready
                note = createDemoNote(sessionId: session.id, specialty: session.specialty)
                uiState = .noteReady
                return
            }
            #endif
            self.error = "Transcription failed: \(error.localizedDescription)"
            stage1Status = .failed(reason: error.localizedDescription)
            AuditLogger.log(
                event: .stage1Failed,
                sessionId: session.id,
                extra: ["reason": String(error.localizedDescription.prefix(200))]
            )
            // Stay in uiState == .processing so the retry prompt remains reachable.
        }
    }

    private func recordStage1Timeout(sessionId: String, since start: Date) {
        let elapsed = Date().timeIntervalSince(start)
        stage1Status = .timedOut(elapsed: elapsed)
        processingStatus = "Stage 1 timed out after \(Int(elapsed))s"
        AuditLogger.log(
            event: .stage1Timeout,
            sessionId: sessionId,
            extra: ["stage1_timeout_ms": "\(Int(elapsed * 1000))"]
        )
        // Stay in uiState == .processing so ProcessingView (and the retry prompt) stay on screen.
    }

    /// Re-fire the Stage 1 pipeline after a timeout/failure. Recorded
    /// audio is still in memory because the session hasn't been torn down.
    func retryStage1() async {
        guard let session else { return }
        AuditLogger.log(event: .stage1Retried, sessionId: session.id)
        error = nil
        await submitAudio()
    }

    // MARK: - Speaker Tagging

    /// Tag transcript segments on-device using the enrolled physician
    /// embedding and PATCH the labels back. The biometric embedding stays
    /// in Keychain — only `(segment_id, speaker, confidence)` crosses the
    /// wire. Best-effort: no enrollment, no PCM buffer, or PATCH failure
    /// all short-circuit silently.
    private func applySpeakerTags(transcript: TranscriptResponse) async {
        guard SpeakerSeparation.shared.isEnrolled else { return }
        guard let buffer = audioSource.getRecordedPCMBuffer() else { return }
        guard !transcript.segments.isEmpty else { return }

        let spans = transcript.segments.map {
            SpeakerSeparation.SegmentTimespan(id: $0.id, startMs: $0.startMs, endMs: $0.endMs)
        }
        let tags = SpeakerSeparation.shared.tagSegments(audio: buffer, segments: spans)
        guard !tags.isEmpty else { return }

        let payload = tags.map {
            SpeakerTagRequest(segmentId: $0.id, speaker: $0.speaker.rawValue, confidence: $0.confidence)
        }
        do {
            _ = try await api.patchSpeakerTags(sessionId: transcript.sessionId, tags: payload)
        } catch {
            #if DEBUG
            print("[SpeakerTagging] PATCH failed: \(error.localizedDescription)")
            #endif
        }
    }

    private func fetchNote() async throws {
        guard let session else { return }
        note = try await api.getStage1Note(sessionId: session.id)
    }

    /// Dismiss the post-encounter sheet without submitting — the user
    /// hit "Back" instead of continuing through template confirmation.
    /// Drops the session back to idle; capture artifacts are retained
    /// until ``endSession`` or the local-data purger runs.
    func dismissPostEncounter() {
        uiState = .idle
    }

    /// Open the note review screen from the noteReady state — the user
    /// tapped "Review Now" on the NoteReadyView.
    func beginReview() {
        uiState = .reviewing
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
        stopScreenCaptureIfRunning()
        session?.clearPersistence()
        session = nil
        note = nil
        uiState = .idle
        processingStatus = ""
        error = nil
        maskingFailedFrames = []
        stage1Status = .idle
    }

    // MARK: - Local data accessors (for LocalDataPurger)

    /// Sum of captured frames across every video capture source in the
    /// registry. Used by the purger to audit-log how much raw video data
    /// was held in memory at purge time.
    var allVideoFrameCount: Int {
        registry.activeSourcesForSession.reduce(0) { count, source in
            count + source.capturedFrames.count
        }
    }

    /// Same idea for the ReplayKit screen capture buffer.
    var allScreenFrameCount: Int { screenCapture.capturedScreenFrames.count }

    /// Size in bytes of the audio PCM held in memory by the active audio
    /// source. Returns 0 if no audio was captured. Goes through the
    /// cheap path (no WAV construction, no buffer copy) so calling it
    /// from purge-audit doesn't allocate the full recording.
    var recordedAudioByteCount: Int {
        audioSource.getRecordedAudioByteCount()
    }

    /// Drop every in-memory raw artifact tied to the current capture
    /// session — video frame arrays, screen frame array, audio PCM. The
    /// session metadata (id, specialty, audit trail) is intentionally
    /// untouched; only the raw clinical bytes go away.
    ///
    /// Idempotent: safe to call multiple times or with no active session.
    func clearCapturedArtifacts() {
        for source in registry.activeSourcesForSession {
            source.capturedFrames = []
        }
        screenCapture.capturedScreenFrames = []
        audioSource.discardRecordedAudio()
        maskingFailedFrames = []
    }

    func endSession() {
        teardownLiveTranscriber()
        stopScreenCaptureIfRunning()
        // Belt-and-suspenders end of the Live Activity. `stopRecording`
        // already ends it on the normal path; covers the abort cases
        // (review dismissed, crash recovery discard, etc.).
        liveActivity.end()
        session?.clearPersistence()
        session = nil
        note = nil
        uiState = .idle
        processingStatus = ""
        error = nil
        maskingFailedFrames = []
        stage1Status = .idle
    }

    /// Adopt a server-side session row (returned by `/sessions`) as the live
    /// in-memory session so the user can return to `CaptureView` and continue
    /// capturing. Used by the dashboard's "Continue Recording" card.
    ///
    /// The iOS capture sources are torn down whenever the app is backgrounded,
    /// so a cold start is required — `pause`/`resume` on the source is a no-op
    /// when `isCapturing == false`. This method handles the full re-engage:
    /// permissions → start sources → backend resume → live transcriber.
    func adoptSession(_ response: SessionResponse) async {
        error = nil
        let mode = CaptureMode(rawValue: response.captureMode) ?? .multimodal
        let captureSession = CaptureSession(
            id: response.id,
            specialty: response.specialty,
            captureMode: mode,
            encounterType: response.encounterType,
            participants: []
        )
        // Past consent — anything in RECORDING/PAUSED on the backend already
        // logged consent_confirmed when this session was first started. We
        // don't know the original method here (backend doesn't expose it
        // yet), so default to `.verbal` — the audit log still has the real
        // event with the real method.
        captureSession.consentMethod = .verbal
        captureSession.consentConfirmedAt = Date()
        captureSession.state = .paused
        session = captureSession
        sessionLanguage = "en"

        // Cold-start the capture pipeline. Permission prompts here are
        // no-ops on subsequent runs.
        await registry.builtIn.ensurePermissions()
        do {
            try await coldStartCapturePipeline(for: mode)
            // Only call backend resume when the server thinks we're paused.
            // If it still says RECORDING the row is already in the right
            // state — we just need iOS to rejoin.
            if SessionState(rawValue: response.state) == .paused {
                _ = try? await api.resumeSession(sessionId: response.id)
            }
            captureSession.startRecording()
            // Resume the Live Activity so the lock-screen pill reflects
            // the recovered session — same UX whether the user is on a
            // cold start or a Continue Recording adopt.
            liveActivity.start(sessionID: response.id, specialty: response.specialty)
        } catch let sourceError as CaptureSourceError {
            self.error = sourceError.localizedDescription
        } catch {
            self.error = "Resume failed: \(error.localizedDescription)"
        }
    }

    // MARK: - Crash Recovery

    /// Validate a session restored from UserDefaults against the backend.
    /// If the server agrees the session is still active in a capture state we
    /// adopt it (cold-start sources, flip to recording, hand off to
    /// `CaptureView`). If the server has advanced past capture (e.g. already
    /// in AWAITING_REVIEW) or never heard of the session, we clear the local
    /// persistence and return false so the caller can route to dashboard.
    func validateRecoveredSession(_ recoveredSession: CaptureSession) async -> Bool {
        do {
            let response = try await api.getSession(sessionId: recoveredSession.id)
            guard let backendState = SessionState(rawValue: response.state) else {
                SessionPersistence.clear()
                return false
            }
            // Only RECORDING / PAUSED warrant a return to CaptureView. Other
            // active states (PROCESSING_STAGE1, AWAITING_REVIEW, etc.) belong
            // in the dashboard's pending-review / processing flows.
            guard backendState == .recording || backendState == .paused else {
                SessionPersistence.clear()
                return false
            }
            await adoptSession(response)
            // adoptSession surfaces source-start errors via `self.error`; treat
            // any such error as "recovery failed" so the caller routes away.
            return self.error == nil
        } catch let error as APIError {
            switch error {
            case .notFound:
                SessionPersistence.clear()
                self.error = "Session expired. Starting fresh."
                return false
            case .offline:
                // No backend — best-effort offline recovery. Cold-start the
                // sources locally so the buttons on CaptureView actually
                // operate on a live pipeline. Backend resume will happen on
                // the next successful network call. Consent metadata was
                // restored from UserDefaults by SessionPersistence.restore.
                recoveredSession.state = .paused
                session = recoveredSession
                await registry.builtIn.ensurePermissions()
                do {
                    try await coldStartCapturePipeline(for: recoveredSession.captureMode)
                    recoveredSession.startRecording()
                    return true
                } catch {
                    self.error = "Offline recovery failed: \(error.localizedDescription)"
                    return false
                }
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

    #if DEBUG
    /// Fabricated note used only when `DemoMode.isEnabled` (Debug builds in
    /// the iOS Simulator). Wrapped in `#if DEBUG` so the function cannot be
    /// compiled into a release/pilot binary. P0-03.
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
    #endif
}
