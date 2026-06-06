import Foundation
import Combine
import SwiftUI
import UIKit

/// Stage 1 SLA (CLAUDE.md §"MVP Success Criteria"): record-stop → note
/// delivered within 30 s for typical sessions. The UI surfaces every
/// phase so the clinician knows whether to wait, retry, or fall back to
/// dictation.
///
/// Marie bug-bash (Bug A) + follow-up: the prior `.timedOut` case was
/// driven by a hard 30-second wall-clock cap that fired spuriously on
/// long sessions (Marie's 3:30min encounter). PR #245 lifted that 30s
/// wall and added a 5-min polling-fallback deadline as a "safety net";
/// the user pushed back — that re-introduced the same class of bug at
/// a higher water mark (a slow LLM cold start or AssemblyAI queue
/// spike on a legitimate recording would still false-fail). The
/// fallback deadline is now removed entirely. Stage 1 delivery is
/// signalled out-of-band via `/ws/notes/{id}`; if the WS drops we
/// poll `GET /notes/{id}/stage1` indefinitely until either the note
/// arrives or the user cancels the session (Task cancellation
/// propagates from the parent flow). `.failed(reason:)` is reached
/// only on explicit backend failure events, never on iOS-side
/// wall-clock expiry.
enum Stage1Status: Equatable {
    case idle
    case uploading
    case generating
    /// Stage 1 is taking a while (≥`stage1LongRunStatusFlipSeconds`).
    /// Same UI as `.generating` but with a reassurance label — no retry
    /// prompt yet. The ring stays parked at 95% until either the WS
    /// event lands or the user cancels.
    case stillWorkingLong
    case ready
    case failed(reason: String)
    /// Recorded offline — the audio is persisted to the on-device upload
    /// queue and will sync automatically on reconnect. Not an error; no retry
    /// prompt (ProcessingView shows a dedicated "saved offline" panel).
    case queuedOffline

    /// When non-nil, ProcessingView shows a retry prompt with this copy.
    ///
    /// Post-Bug-A: copy is timeout-neutral so it covers any backend
    /// failure mode (provider error, 5xx, fallback-poll deadline).
    /// Pulled from Localizable so EN/FR parity is enforced.
    ///
    /// lane-ios/audio-upload-resilience: the `reason` payload on
    /// `.failed` now carries a pre-localized detail string (one of the
    /// `audio_upload_failed_*` keys from Localizable). Callers used to
    /// drop it in favour of the generic stage1Failed.detail; we surface
    /// it directly so "couldn't reach the server" and "audio file
    /// couldn't be saved" land different copy on the same retry
    /// prompt. Empty reason falls back to the generic message — keeps
    /// the existing "Stage 1 backend failed" path intact.
    var retryPrompt: (title: String, detail: String)? {
        switch self {
        case .failed(let reason):
            let detail = reason.isEmpty
                ? L("processing.stage1Failed.detail")
                : reason
            return (L("processing.stage1Failed.title"), detail)
        case .idle, .uploading, .generating, .stillWorkingLong, .ready, .queuedOffline:
            return nil
        }
    }
}

/// One-shot WebSocket subscriber that listens on `/ws/notes/{session_id}`
/// for the backend's `stage1_delivered` push and signals via `waitForReady`.
///
/// Why a private helper instead of reusing `WebSocketClient`:
///   * Stage 1 needs a one-shot AWAIT semantic — open the channel
///     BEFORE the upload POST so the push can't race, suspend on the
///     event, return a Bool the caller can use to fall back to polling.
///     `WebSocketClient` is a longer-lived `@StateObject` driving SwiftUI
///     state on `NoteReviewView`; its `latestNote` publishing model
///     doesn't fit a one-shot await without contortions.
///   * Keeping the wait helper local also means a future WS schema
///     change can be absorbed in one place without coordinating with
///     the broader Network/ surface.
///
/// lane-ios/audio-upload-resilience (PR #243) introduced
/// `WebSocketEvent` in `WebSocketClient.swift` — the broken-on-Stage1
/// path on `WebSocketClient.latestNote` is fixed there. This helper
/// continues to do its own envelope read for the one-shot semantic;
/// the two paths share the same backend payload shape.
///
/// This subscriber decodes the envelope, checks for `event ==
/// "stage1_delivered"`, and resolves a continuation so the SessionManager
/// caller can await the push without polling.
///
/// Lifetime: `start()` once per audio-submit attempt, `cancel()` on
/// every exit path (success, failure, defer). Calling `waitForReady`
/// after `cancel()` returns `false` immediately so the caller can fall
/// back to polling.
@MainActor
private final class Stage1WSSubscriber {
    private let sessionId: String
    private var task: URLSessionWebSocketTask?
    private var continuation: CheckedContinuation<Bool, Never>?
    /// True once the WS task has either delivered the event or been
    /// torn down. Subsequent waiters short-circuit so the caller never
    /// blocks on a dead subscriber.
    private var finished = false

    init(sessionId: String) {
        self.sessionId = sessionId
    }

    func start() {
        guard let url = URL(string: "\(AppConfig.wsBaseURL)/ws/notes/\(sessionId)") else {
            // Bad config — treat as "WS not available" so caller falls
            // back to polling immediately.
            finished = true
            return
        }
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        listen()
    }

    /// Suspend until `stage1_delivered` arrives, the WS drops, or the
    /// subscriber is cancelled. Returns `true` when the event was seen,
    /// `false` otherwise — caller should then fall back to polling.
    func waitForReady() async -> Bool {
        if finished {
            return false
        }
        return await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            self.continuation = cont
        }
    }

    /// Tear down the WS task without resolving the continuation as
    /// "ready". Idempotent. The deferred `cancel()` in submitAudio's
    /// happy path is a no-op when `finalize(ready:)` already fired.
    func cancel() {
        finalize(ready: false)
    }

    private func listen() {
        task?.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .failure:
                    // WS closed (clean or otherwise) — let the caller
                    // fall back to polling.
                    self.finalize(ready: false)
                case .success(let message):
                    let payloadData: Data?
                    switch message {
                    case .string(let text): payloadData = text.data(using: .utf8)
                    case .data(let data): payloadData = data
                    @unknown default: payloadData = nil
                    }
                    if let data = payloadData,
                       let envelope = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let event = envelope["event"] as? String,
                       event == "stage1_delivered" {
                        self.finalize(ready: true)
                        return
                    }
                    // Any other event (stage2_progress, stage2_delivered,
                    // unknown future events) — keep listening; Stage 1
                    // hasn't fired yet.
                    self.listen()
                }
            }
        }
    }

    private func finalize(ready: Bool) {
        guard !finished else { return }
        finished = true
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        continuation?.resume(returning: ready)
        continuation = nil
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

/// A frame OR clip that failed on-device masking, tagged with its
/// origin so the retry path knows which endpoint to re-fire (video →
/// `/frames`, screen → `/screen`, clip → `/clips`). Conflating them
/// silently routed screen retries to the video endpoint.
///
/// P1-5 widened `Kind` to include `.clip`. Clip failures don't have a
/// `CapturedFrame` payload — the source bytes lived in the
/// VideoRingBuffer's raw MP4, which `MaskingPipeline.maskClip` consumed
/// and then deleted. The retry path can re-extract from the ring buffer
/// only while the session is still live; after stop, a failed clip is
/// surfaced for skip/acknowledge rather than retry.
struct FailedMaskingFrame: Identifiable {
    enum Kind { case video, screen, clip }
    /// Populated for `.video` and `.screen` failures. Nil for `.clip` —
    /// the clip path doesn't have a CapturedFrame; see `clipTrigger`.
    let frame: CapturedFrame?
    let kind: Kind
    /// Populated for `.clip` failures. The trigger that drove the clip
    /// extraction; the retry path uses `trigger.timestamp` to ask the
    /// ring buffer for the same window again.
    let clipTrigger: TriggerEvent?
    let _id: UUID
    var id: UUID { _id }

    init(frame: CapturedFrame, kind: Kind) {
        precondition(kind != .clip, "FailedMaskingFrame.init(frame:kind:) is for .video / .screen only")
        self.frame = frame
        self.kind = kind
        self.clipTrigger = nil
        self._id = frame.id
    }

    init(clipTrigger: TriggerEvent) {
        self.frame = nil
        self.kind = .clip
        self.clipTrigger = clipTrigger
        self._id = UUID()
    }
}

/// Manages the full session lifecycle -- bridges iOS UI to backend API.
@MainActor
final class SessionManager: ObservableObject {
    @Published var session: CaptureSession?
    @Published var note: NoteResponse?
    @Published private(set) var uiState: SessionUIState = .idle {
        didSet { handleProcessingProgress(from: oldValue, to: uiState) }
    }
    @Published var processingStatus = ""
    /// 0.0–1.0 estimated progress for the processing screen. Animated
    /// 0 → 0.95 over the Stage 1 SLA window (~25s) the moment uiState
    /// becomes ``.processing``; held at 0.95 if the backend runs longer;
    /// reset to 0.0 outside of processing. Time-based estimate, not
    /// true progress — the backend doesn't emit per-step events today.
    @Published var processingProgress: Double = 0.0
    private var processingProgressTask: Task<Void, Never>?
    @Published var error: String?
    @Published var stage1Status: Stage1Status = .idle
    /// Wall-clock when the capture pipeline last began streaming. Used by
    /// the CaptureView's stop button to enforce the minimum recording
    /// duration so the audio delegate has time to deliver its first
    /// buffer (warm-up is typically ~500ms but can exceed 1s on cold
    /// AVAudioSession activation). Reset on stop.
    @Published private(set) var recordingStartedAt: Date?

    /// On-disk WAV for the current session, persisted from the
    /// CaptureManager's in-memory PCM at the top of `submitAudio` so the
    /// upload chain (`AudioUploadCoordinator`) has a stable byte source
    /// it can retry from across:
    ///
    ///   * coordinator-internal exponential backoff (3 attempts inside
    ///     one `submitAudio` call), and
    ///   * the clinician-driven Retry button (`retryStage1` re-runs the
    ///     upload from the SAME file — Bug 2: previously Retry no-op'd
    ///     because the upload had never reached the backend and there
    ///     was no on-disk source to replay from).
    ///
    /// Lifecycle:
    ///   1. Set inside `submitAudio` after `persistRecordedAudio` lands
    ///      bytes to disk and emits `recording_file_finalized`.
    ///   2. Read by both the initial upload and any Retry attempts.
    ///   3. Cleared + file deleted by `clearRecordedAudioFile` once the
    ///      backend ACKs the upload (the transcription endpoint returns
    ///      202 after the bytes are in S3; the backend's cleanup module
    ///      owns the post-transcription deletion).
    ///   4. ALSO cleared by `endSession` / `clearCapturedArtifacts` so a
    ///      torn-down session doesn't leak its raw audio across boots.
    ///
    /// Note this URL lives under Application Support (NOT the temporary
    /// directory) so an iOS sandbox cleanup doesn't yank it out from
    /// under the retry path. The OfflineUploadQueue uses the same
    /// directory for the same reason — both audio paths share the
    /// "raw clinical bytes never under iOS's discretionary sweep" rule.
    private var recordedAudioFileURL: URL?

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

    /// Read-accessor used by LivePreviewOverlay (#64) so the preview
    /// generation request carries the physician's chosen output
    /// language without leaking the private `sessionLanguage` storage
    /// to the broader view layer.
    var sessionLanguageForLivePreview: String { sessionLanguage }

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
                participants: participants,
                providerOverrides: response.providerOverrides
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

    /// URLError codes that mean "the request couldn't land" — no network, or
    /// the backend host is unreachable. Mirrors APIClient's offline mapping so
    /// the raw-URLSession audio upload classifies failures the same way.
    private static let offlineURLErrorCodes: Set<URLError.Code> = [
        .notConnectedToInternet, .networkConnectionLost,
        .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed,
    ]

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
        // pause() (not stop()) so the accumulated caption text survives the
        // pause/resume cycle and stays frozen on screen until recording
        // continues. stop() is reserved for end-of-session teardown.
        liveTranscriber?.pause()
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
        // Granular audit (lane-ios/audio-upload-resilience). Fires the
        // instant the clinician taps Stop, BEFORE we touch the capture
        // sources. Pairs with `recording_file_finalized` later — the
        // delta between the two is "how long did the in-memory PCM take
        // to settle." Before this event, Marie's 3:30min session went
        // silent between `recording_started` and `stage1_started` and
        // we couldn't tell whether the stop intent landed or not.
        AuditLogger.log(event: .recordingStopInitiated, sessionId: session.id)
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
        } catch APIError.offline {
            // Backend unreachable — don't strand the physician on the capture
            // screen. Advance locally so the encounter can be confirmed and
            // persisted to the offline queue; the queue replays the stop
            // transition + audio upload when connectivity returns.
            session.stopRecording()
            uiState = .postEncounter
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
        // Offline: skip the per-frame Stage 2 uploads (each needs the network
        // and would just fail) and persist the audio to the offline queue so
        // the encounter — and its Stage 1 note — is never lost. The queue
        // replays the stop transition + upload on reconnect.
        if !ReachabilityMonitor.shared.isOnline {
            await queueAudioOffline()
            return
        }
        await submitVisualEvidence()
        await submitAudio()
        // Screen frames merge into the note AFTER Stage 1 generated it,
        // so this runs last. The screen pipeline is fully on-device for
        // PHI; the upload carries the masking proof from P0-02.
        await submitScreenFrames()
    }

    /// Persist the recorded audio to the on-device upload queue for deferred
    /// sync. Called when there's no connectivity at submit time, or when the
    /// interactive upload fails offline mid-flight. Frees the in-memory PCM
    /// (and any upload-staging WAV) once the offline queue has accepted the
    /// bytes.
    ///
    /// lane-ios/audio-upload-resilience: prefer the on-disk staged WAV
    /// when present — the upload chain may have already persisted bytes
    /// and discarded the in-memory PCM by the time we land here on a
    /// "went offline mid-upload" failure path.
    private func queueAudioOffline() async {
        guard let session else { return }
        let audio: Data
        if let stagedURL = recordedAudioFileURL,
           FileManager.default.fileExists(atPath: stagedURL.path),
           let stagedBytes = try? Data(contentsOf: stagedURL),
           !stagedBytes.isEmpty {
            audio = stagedBytes
        } else if let liveBytes = audioSource.getRecordedAudioData(), !liveBytes.isEmpty {
            audio = liveBytes
        } else {
            // No bytes anywhere (staged file gone AND in-memory PCM
            // empty) — almost always a too-short recording. Same
            // surface as the online path.
            self.error = L("audio_upload_failed_too_short")
            stage1Status = .failed(reason: L("audio_upload_failed_too_short"))
            return
        }
        do {
            try OfflineUploadQueue.shared.enqueue(
                sessionId: session.id,
                specialty: session.specialty,
                audio: audio
            )
            audioSource.discardRecordedAudio()
            // The bytes now live in the OfflineUploadQueue's own
            // directory — drop the staged copy so we don't have two
            // copies of the raw audio on disk.
            clearRecordedAudioFile()
            stage1Status = .queuedOffline
            processingStatus = ""
            AuditLogger.log(
                event: .audioQueuedOffline,
                sessionId: session.id,
                extra: ["bytes": "\(audio.count)"]
            )
        } catch {
            // OfflineUploadQueue.enqueue couldn't land the WAV (disk
            // full / sandbox issue / etc.). Surface with the file-
            // failure copy — same root cause as a primary write
            // failure. PHI-clean: no `error.localizedDescription` —
            // it can echo file paths under .applicationSupportDirectory
            // that aren't PHI per se but are noisier than this layer
            // needs.
            self.error = L("audio_upload_failed_file")
            stage1Status = .failed(reason: L("audio_upload_failed_file"))
        }
    }

    // MARK: - Visual Evidence Submission (P1-5 dual-mode)

    /// Resolve which `VisualEvidenceMode` to use for a session — the
    /// session-level override (P1-7) wins when set and parseable;
    /// everything else falls back to the AppConfig global default.
    ///
    /// Static + pure so unit tests can exercise it without spinning
    /// up a SessionManager / RemoteConfig. The Stage 2 dispatcher
    /// calls this once at the top of `submitVisualEvidence` so the
    /// per-frame `extractEvidence` switch only sees a single
    /// resolved mode (LSP — same enum the AppConfig path returns).
    ///
    /// `sessionOverride` is the RAW string from
    /// `session.providerOverrides?.visualEvidenceMode`. An
    /// unparseable string is treated as "no override" — fail-soft,
    /// never crash the dispatcher on a stale row or a future server
    /// that emits a mode this iOS build doesn't know yet. A debug
    /// log line lets the verification gate spot the silent fallback.
    nonisolated static func resolveEvidenceMode(
        sessionOverride: String?,
        globalDefault: VisualEvidenceMode
    ) -> VisualEvidenceMode {
        guard let raw = sessionOverride, !raw.isEmpty else {
            return globalDefault
        }
        if let parsed = VisualEvidenceMode(rawValue: raw) {
            return parsed
        }
        // Unparseable — log and fall back. No PHI: the raw string is
        // an AppConfig enum value, never patient content.
        print("[SessionManager] Unparseable session visual_evidence_mode override='\(raw)' — falling back to global default '\(globalDefault.rawValue)'")
        return globalDefault
    }

    /// Resolve the captured frame list into a list of `VisualEvidence`
    /// items per the active `VisualEvidenceMode`. Pure helper — no I/O
    /// — so unit tests can exercise the dispatch logic with a stubbed
    /// mode and trigger list.
    ///
    /// - `.framesOnly`: each captured frame becomes a `.frame(...)`. No
    ///   clip extraction, no ring-buffer work — byte-identical to the
    ///   pre-P1-5 path.
    /// - `.clipsOnly`: each captured frame is treated as a clip trigger;
    ///   the ring buffer is asked for a window of `clipWindowMs` around
    ///   the frame's timestamp. Caller awaits the extraction.
    /// - `.hybrid`: per-frame routing keyed on whether the synthetic
    ///   trigger kind (defaulting to `"clinic"`) is in `clipTriggerKinds`.
    ///   Today every captured frame is treated as `"clinic"` because the
    ///   trigger classifier ships in a later PR — see Out of scope in
    ///   the P1-5 plan.
    ///
    /// The trigger kind for a frame-derived evidence item is set to the
    /// caller-supplied default so a future classifier (which will emit
    /// real motion/rom/gait/procedural kinds) can plug in without
    /// reshaping the dispatcher.
    func extractEvidence(
        for trigger: TriggerEvent,
        mode: VisualEvidenceMode,
        clipWindowMs: Int,
        clipTriggerKinds: [String],
        capturedFrame: CapturedFrame?,
        ringBuffer: VideoRingBuffer?
    ) async throws -> VisualEvidence {
        switch mode {
        case .framesOnly:
            guard let capturedFrame else {
                throw NSError(
                    domain: "AurionDispatcher",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "framesOnly mode requires a CapturedFrame"]
                )
            }
            return .frame(capturedFrame)
        case .clipsOnly:
            return try await buildClipEvidence(
                trigger: trigger,
                clipWindowMs: clipWindowMs,
                ringBuffer: ringBuffer
            )
        case .hybrid:
            if clipTriggerKinds.contains(trigger.kind) {
                return try await buildClipEvidence(
                    trigger: trigger,
                    clipWindowMs: clipWindowMs,
                    ringBuffer: ringBuffer
                )
            }
            guard let capturedFrame else {
                // Hybrid with a frame-kind trigger but no captured frame —
                // emit a clip if the ring buffer is available, otherwise
                // bubble up.
                return try await buildClipEvidence(
                    trigger: trigger,
                    clipWindowMs: clipWindowMs,
                    ringBuffer: ringBuffer
                )
            }
            return .frame(capturedFrame)
        }
    }

    private func buildClipEvidence(
        trigger: TriggerEvent,
        clipWindowMs: Int,
        ringBuffer: VideoRingBuffer?
    ) async throws -> VisualEvidence {
        guard let ringBuffer else {
            throw NSError(
                domain: "AurionDispatcher",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "clipsOnly/hybrid mode requires a VideoRingBuffer"]
            )
        }
        let duration = TimeInterval(clipWindowMs) / 1000.0
        let url = try await ringBuffer.extract(around: trigger.timestamp, duration: duration)
        return .clip(url, duration: clipWindowMs, trigger: trigger)
    }

    /// Mask + upload every visual evidence item captured during the
    /// session. Replaces the pre-P1-5 `submitFrames` — backward-compatible
    /// in default mode (`.framesOnly`) because every captured frame still
    /// flows through the same `maskVideoFrame` → `uploadFrame` path.
    ///
    /// Routing:
    /// - `.frame` → existing path (`MaskingPipeline.maskVideoFrame` +
    ///   `APIClient.uploadFrame`).
    /// - `.clip` → new path (`MaskingPipeline.maskClip` +
    ///   `APIClient.uploadClip`). Fail-closed on masking failure — the
    ///   masked file is never produced in that branch so we can't
    ///   accidentally upload it.
    ///
    /// Per-evidence network failures are non-fatal — we keep uploading
    /// the rest. Per-evidence MASKING failures quarantine into
    /// `maskingFailedFrames` so the UI can surface skip/retry.
    private func submitVisualEvidence() async {
        guard let session, let videoSource = registry.activeVideoSource else { return }
        let frames = videoSource.capturedFrames
        guard !frames.isEmpty else { return }

        processingStatus = "Uploading frames…"
        maskingFailedFrames.removeAll { $0.kind == .video || $0.kind == .clip }

        let pipeline = RemoteConfig.shared.pipeline
        // Session-level override (P1-7) takes precedence over the
        // AppConfig-driven global default. The resolver returns the
        // global mode whenever no session override is set OR the
        // override carries an unparseable string — fail-soft, never
        // crash the dispatcher on a corrupt override.
        let mode = Self.resolveEvidenceMode(
            sessionOverride: session.providerOverrides?.visualEvidenceMode,
            globalDefault: pipeline.visualEvidenceMode
        )
        let clipWindowMs = pipeline.clipWindowMs
        let clipTriggerKinds = pipeline.clipTriggerKinds

        // The trigger classifier lands later; today every captured frame
        // is treated as a `"clinic"` kind trigger so hybrid mode routes
        // it to the frame path by default. This is the safe choice
        // pre-classifier: nothing escapes to the clip path until the
        // backend declares its trigger taxonomy.
        let defaultTriggerKind = "clinic"

        // Ring buffer lives on the BuiltInCaptureSource's underlying
        // manager. Look it up once outside the per-frame loop.
        let ringBuffer = (videoSource as? BuiltInCaptureSource)?.clipRingBuffer

        var framesUploaded = 0
        var clipsUploaded = 0
        var maskingFailed = 0
        var total = 0

        for frame in frames {
            total += 1
            let trigger = TriggerEvent(
                kind: defaultTriggerKind,
                timestamp: frame.timestamp,
                segmentId: "frame_\(Int((frame.timestamp * 1000).rounded()))"
            )

            let evidence: VisualEvidence
            do {
                evidence = try await extractEvidence(
                    for: trigger,
                    mode: mode,
                    clipWindowMs: clipWindowMs,
                    clipTriggerKinds: clipTriggerKinds,
                    capturedFrame: frame,
                    ringBuffer: ringBuffer
                )
            } catch {
                // Couldn't build evidence (e.g., ring buffer empty) —
                // log and continue. Not a masking failure; nothing was
                // produced to upload in the first place.
                continue
            }

            // Mask via the polymorphic entry — same call regardless of
            // evidence kind. Result carries the kind-specific payload
            // (imageData for frame, maskedFileURL for clip).
            let result = await MaskingPipeline.shared.mask(evidence, sessionId: session.id)
            guard result.success else {
                maskingFailed += 1
                switch evidence {
                case .frame(let captured):
                    maskingFailedFrames.append(FailedMaskingFrame(frame: captured, kind: .video))
                case .clip(let url, _, let clipTrigger):
                    // Best-effort cleanup of the RAW clip input — masking
                    // failed, so we shouldn't keep raw video lingering
                    // on disk.
                    try? FileManager.default.removeItem(at: url)
                    maskingFailedFrames.append(FailedMaskingFrame(clipTrigger: clipTrigger))
                }
                continue
            }

            switch evidence {
            case .frame(let captured):
                guard let maskedData = result.imageData else {
                    maskingFailed += 1
                    maskingFailedFrames.append(FailedMaskingFrame(frame: captured, kind: .video))
                    continue
                }
                let timestampMs = Int((captured.timestamp * 1000).rounded())
                do {
                    _ = try await api.uploadFrame(
                        sessionId: session.id,
                        jpegData: maskedData,
                        timestampMs: timestampMs,
                        frameType: result.frameType.rawValue,
                        facesDetected: result.facesDetected,
                        phiRegionsRedacted: result.phiRegionsRedacted
                    )
                    framesUploaded += 1
                } catch {
                    continue
                }

            case .clip(let rawClipURL, let durationMs, let clipTrigger):
                // The raw input MP4 served its purpose — masking produced
                // a NEW masked MP4 at result.maskedFileURL. Delete the
                // raw bytes before crossing any network boundary.
                try? FileManager.default.removeItem(at: rawClipURL)

                guard let maskedURL = result.maskedFileURL else {
                    maskingFailed += 1
                    maskingFailedFrames.append(FailedMaskingFrame(clipTrigger: clipTrigger))
                    continue
                }
                let timestampMs = Int((clipTrigger.timestamp * 1000).rounded())
                do {
                    _ = try await api.uploadClip(
                        sessionId: session.id,
                        clipFileURL: maskedURL,
                        timestampMs: timestampMs,
                        durationMs: durationMs,
                        triggerSegmentId: clipTrigger.segmentId,
                        framesTotal: result.framesTotal,
                        framesWithFaces: result.framesWithFaces
                    )
                    clipsUploaded += 1
                } catch {
                    // Network failure — keep going; clean up the masked
                    // file so it doesn't leak across the session boundary.
                }
                // Always clean up the masked file after the upload
                // attempt (success or failure) — the backend has the
                // bytes, or the upload failed and there's no retry path
                // post-stop.
                try? FileManager.default.removeItem(at: maskedURL)
            }
        }

        processingStatus = composeUploadStatus(
            total: total,
            framesUploaded: framesUploaded,
            clipsUploaded: clipsUploaded,
            maskingFailed: maskingFailed
        )
    }

    /// Build the `processingStatus` user-facing string for the mixed
    /// frame+clip upload path. Pulled out so the formatting logic isn't
    /// inlined three times in `submitVisualEvidence`.
    ///
    /// Examples:
    /// - 3 frames uploaded                 (frames-only mode, no failures)
    /// - 2 clips uploaded                  (clips-only mode, no failures)
    /// - 3 frames + 2 clips uploaded       (hybrid mode, both kinds)
    /// - 1 frame uploaded · 1 failed masking
    /// - 0 uploaded · 2 failed masking
    private func composeUploadStatus(
        total: Int,
        framesUploaded: Int,
        clipsUploaded: Int,
        maskingFailed: Int
    ) -> String {
        var parts: [String] = []
        if framesUploaded > 0 {
            parts.append("\(framesUploaded) frame\(framesUploaded == 1 ? "" : "s")")
        }
        if clipsUploaded > 0 {
            parts.append("\(clipsUploaded) clip\(clipsUploaded == 1 ? "" : "s")")
        }
        let uploadedDescription: String
        if parts.isEmpty {
            uploadedDescription = "0"
        } else {
            uploadedDescription = parts.joined(separator: " + ")
        }
        var status = "\(uploadedDescription) uploaded"
        if maskingFailed > 0 {
            status += " · \(maskingFailed) failed masking"
        }
        _ = total // total reserved for a future "uploaded/total" surface; intentionally unused today
        return status
    }

    /// Re-run masking + upload for any frames that previously failed masking.
    /// Called when the clinician chooses "Retry" on the masking-failure prompt.
    /// Dispatches by `kind` so video → `/frames` and screen → `/screen` —
    /// uploading a screen frame to the wrong endpoint would let unredacted
    /// PHI through to S3.
    ///
    /// Clip failures are NOT retried here — the source bytes lived only in
    /// the VideoRingBuffer at extraction time; by submit time the buffer
    /// is already cleared and the raw MP4 deleted. Clip failures are
    /// presented as skip-only in the UI.
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
            // Clip failures can't be retried post-session — preserve them
            // in the quarantine list so the UI can offer skip-only.
            guard failed.kind != .clip, let frame = failed.frame else {
                stillFailed += 1
                maskingFailedFrames.append(failed)
                continue
            }
            guard let image = UIImage(data: frame.imageData) else {
                stillFailed += 1
                maskingFailedFrames.append(failed)
                continue
            }
            let timestampMs = Int((frame.timestamp * 1000).rounded())
            let masked: MaskingResult
            switch failed.kind {
            case .video:
                masked = await MaskingPipeline.shared.maskVideoFrame(image, sessionId: session.id)
            case .screen:
                masked = await MaskingPipeline.shared.redactScreenCapture(image, sessionId: session.id)
            case .clip:
                continue // unreachable — short-circuited above
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
                case .clip:
                    continue // unreachable
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
    //
    // Bug A (Marie bug-bash) — Stage 1 used to be gated by a 30-second
    // hard wall-clock cap on the URLSession (both `timeoutIntervalForRequest`
    // and `timeoutIntervalForResource`). Marie's 3:30min session hit this
    // and surfaced as "Stage 1 timed out after 30s" with a non-functional
    // Retry. The new flow:
    //
    //  1. Open `/ws/notes/{id}` BEFORE the upload POST so we never miss
    //     the push (the backend can fire it the instant the note lands).
    //  2. POST the audio with the 5-min upload cap from AppConfig (this
    //     is upload-bytes, not Stage 1 latency).
    //  3. After 2xx, await either the WS `stage1_delivered` event or a
    //     fallback poll-with-deadline if the WS drops.
    //  4. At ~45s, swap the processing label to a reassurance string;
    //     the ring stays parked at 95%. No hard timeout — only failure
    //     paths are "backend said failed", "fallback poll deadline", or
    //     a real URLSession error.
    //
    // lane-ios/audio-upload-resilience adds a layer below Bug A: the
    // POST itself now goes through `AudioUploadCoordinator` — a
    // background-configured URLSession with retry-with-backoff (3
    // attempts), progress callbacks at 25/50/75%, and a classified
    // failure category that we can route to a specific localized
    // user-facing message. The previous fire-and-forget URLSession
    // call lost Marie's session at the upload boundary: backend audit
    // showed `recording_started → stage1_started` and then silence
    // because the POST was suspended when she backgrounded the app
    // and the foreground ephemeral session silently dropped it.
    //
    // The audio bytes are persisted to disk in
    // `persistRecordedAudio` BEFORE the upload starts, so:
    //  * the coordinator's per-attempt retry loop reads from the
    //    same on-disk WAV (eliminates the in-memory PCM as a single
    //    point of failure mid-upload), and
    //  * Bug 2: the clinician-facing Retry button (`retryStage1`)
    //    re-runs the upload from the same file rather than no-op'ing
    //    against an upload that never happened.

    private func submitAudio() async {
        guard let session else { return }
        uiState = .processing

        let captureSessionId = session.id
        let captureSpecialty = session.specialty

        // ── Step 0: lock the audio bytes onto disk so the upload chain
        // has a stable source. If a previous `submitAudio` already
        // persisted the WAV (Retry path), reuse it instead of round-
        // tripping through the in-memory accumulator — `discardRecordedAudio`
        // wipes the PCM after persist, so on retry the accumulator is
        // empty and we'd otherwise misclassify a real recording as
        // too-short.
        let persistedFile: PersistedAudio
        do {
            persistedFile = try persistRecordedAudioIfNeeded(
                sessionId: captureSessionId
            )
        } catch let error as PersistError {
            // Distinct branches by why persist failed:
            //  * `.empty` → almost always too-short recording.
            //  * `.writeFailed` → disk full, sandbox issue.
            //  * `.recordingLost` → retry path, file vanished.
            switch error {
            case .empty:
                // Empty audioPCMData means the AVAudioSession delegate never
                // delivered a buffer. In practice this is almost always a
                // too-short recording — the stop-button guard below the start
                // timestamp should catch most of these, but on first-launch
                // mic warmup or a backgrounded session it's still possible.
                self.error = L("audio_upload_failed_too_short")
                stage1Status = .failed(reason: L("audio_upload_failed_too_short"))
                AuditLogger.log(
                    event: .recordingFinalizationFailed,
                    sessionId: captureSessionId,
                    extra: ["reason": "empty_buffer"]
                )
                return
            case .writeFailed:
                self.error = L("audio_upload_failed_file")
                stage1Status = .failed(reason: L("audio_upload_failed_file"))
                AuditLogger.log(
                    event: .recordingFinalizationFailed,
                    sessionId: captureSessionId,
                    extra: ["reason": "disk_write_failed"]
                )
                return
            case .recordingLost:
                self.error = L("audio_upload_recording_lost")
                stage1Status = .failed(reason: L("audio_upload_recording_lost"))
                AuditLogger.log(
                    event: .recordingFinalizationFailed,
                    sessionId: captureSessionId,
                    extra: ["reason": "file_missing_on_retry"]
                )
                return
            }
        } catch {
            // Unreachable in practice — persistRecordedAudioIfNeeded
            // only throws `PersistError`. Belt-and-suspenders so a
            // future helper extension doesn't slip through.
            self.error = L("audio_upload_failed_file")
            stage1Status = .failed(reason: L("audio_upload_failed_file"))
            return
        }

        // Audit only on the first persist (not on retry re-uploads from
        // the same on-disk file) — `recording_file_finalized` is the
        // "finalization landed bytes on disk" event, NOT "we're starting
        // an upload" (that's `audio_upload_started` below).
        if persistedFile.wasFreshlyWritten {
            AuditLogger.log(
                event: .recordingFileFinalized,
                sessionId: captureSessionId,
                extra: ["file_bytes": "\(persistedFile.bytes)"]
            )
        }

        // From here on the in-memory PCM is no longer the source of
        // truth — the on-disk WAV is. The accumulator is freed on the
        // happy path by `clearRecordedAudioFile` after the backend
        // ACKs the upload (HTTP 2xx).
        let fileURL = persistedFile.url
        let bytes = persistedFile.bytes

        stage1Status = .uploading
        processingStatus = L("processing.uploadingAudio")
        let stage1Start = Date()

        // ── Step 1: open the push channel BEFORE the upload POST. The
        // backend fires `stage1_delivered` the instant the note lands;
        // if the WS wasn't already connected, we'd miss it. The
        // subscription completes when the event arrives OR the WS task
        // is explicitly cancelled (we cancel in the failure paths).
        let stage1Ready = Stage1WSSubscriber(sessionId: captureSessionId)
        stage1Ready.start()

        // ── Step 1b: schedule the "still working" status flip at 45s.
        // Pure UX — no audit event, no state change. Cancelled when we
        // leave the audio-submit path.
        let longRunFlipTask = scheduleStage1LongRunStatusFlip()

        defer {
            stage1Ready.cancel()
            longRunFlipTask?.cancel()
        }

        // ── Step 2: drive the upload through AudioUploadCoordinator.
        // The coordinator owns:
        //   * a background-configured URLSession (survives backgrounding
        //     mid-upload — was the proximate cause of Marie's
        //     silent-after-recording_started failure mode), and
        //   * a 3-attempt retry loop with exponential backoff for
        //     classify-as-retryable URLErrors and 5xx responses.
        //
        // We forward each attempt boundary into the audit trail so the
        // backend dashboards can chart "fail on first try" vs "fail
        // after every retry."
        AuditLogger.log(
            event: .audioUploadStarted,
            sessionId: captureSessionId,
            extra: ["file_bytes": "\(bytes)"]
        )

        let token = KeychainHelper.shared.bearerToken()
        let uploadStart = Date()

        do {
            // `stage1Status` stays `.uploading` until the coordinator
            // returns 2xx — at that point the bytes are server-side and
            // we're waiting on Stage 1 generation, which is the
            // `.generating` semantic. Flipping pre-emptively (the
            // pre-PR-#243 code did) showed the clinician "generating"
            // before the bytes even left the phone, hiding network
            // failures behind a misleading status.
            let data = try await AudioUploadCoordinator.shared.upload(
                fileURL: fileURL,
                sessionId: captureSessionId,
                bearerToken: token,
                bytes: bytes,
                maxAttempts: 3,
                onAttemptStart: { _ in
                    // Per-attempt audit not emitted today — `audio_upload_started`
                    // covers the chain, and per-attempt-failure is logged
                    // below. We have onAttemptStart wired so future
                    // observability work can plug in without re-shaping
                    // the coordinator API.
                },
                onAttemptFailure: { attempt, category in
                    // Each non-final attempt failure is its own audit
                    // event so we can tell "failed once, retried,
                    // succeeded" from "failed three times, gave up."
                    // The terminal failure also emits `audio_upload_failed`
                    // below; this is the per-attempt slice.
                    Task { @MainActor in
                        AuditLogger.log(
                            event: .audioUploadFailed,
                            sessionId: captureSessionId,
                            extra: [
                                "attempt": "\(attempt)",
                                "error_category": category.rawValue,
                                "terminal": "false",
                            ]
                        )
                    }
                },
                onProgress: { bytesSent, bytesTotal in
                    // The coordinator only fires onProgress at the
                    // 25/50/75 thresholds — pre-filtered there, so we
                    // can just emit one audit event per callback.
                    let percent = bytesTotal > 0
                        ? Int((Double(bytesSent) / Double(bytesTotal)) * 100)
                        : 0
                    Task { @MainActor in
                        AuditLogger.log(
                            event: .audioUploadProgress,
                            sessionId: captureSessionId,
                            extra: [
                                "bytes_sent": "\(bytesSent)",
                                "bytes_total": "\(bytesTotal)",
                                "percent": "\(percent)",
                            ]
                        )
                    }
                }
            )

            let uploadElapsedMs = Int(Date().timeIntervalSince(uploadStart) * 1000)
            AuditLogger.log(
                event: .audioUploadSucceeded,
                sessionId: captureSessionId,
                extra: [
                    "elapsed_ms": "\(uploadElapsedMs)",
                    "file_bytes": "\(bytes)",
                ]
            )

            // Bytes are server-side now — flip the status so the
            // processing UI flips from "uploading" copy to "generating
            // note…" while we await Stage 1 over WS/poll.
            stage1Status = .generating
            processingStatus = L("processing.generatingNote")

            // Backend ACK'd the bytes (HTTP 2xx). Drop the on-disk WAV
            // and the in-memory PCM — both have been replaced by the
            // backend-side S3 object the cleanup module will purge per
            // its TTL. Keeping the WAV around past this point would
            // leak raw clinical audio across the next session boundary.
            clearRecordedAudioFile()
            audioSource.discardRecordedAudio()

            // Speaker tagging is best-effort; the voice embedding stays in
            // Keychain. Failure here doesn't block note generation.
            if let transcript = try? JSONDecoder().decode(TranscriptResponse.self, from: data) {
                await applySpeakerTags(transcript: transcript)
            }

            // ── Step 3: wait for the WS push, or fall back to polling
            // (unbounded) if the channel drops. Either way we then
            // `fetchNote()` over REST — the WS payload carries the note
            // inline, but the existing iOS plumbing assumes the
            // canonical store comes from `GET /notes/{id}/stage1`, so
            // we stay consistent and re-read it. Cheap enough.
            //
            // No wall-clock deadline here (intentionally): the helper
            // polls until the note arrives or the parent Task is
            // cancelled. See awaitStage1Ready docstring for why.
            await awaitStage1Ready(
                subscription: stage1Ready,
                sessionId: captureSessionId
            )

            try await fetchNote()
            stage1Status = .ready
            processingStatus = L("processing.noteReady")
            uiState = .noteReady
        } catch let uploadError as AudioUploadError {
            // Terminal failure after the coordinator's retry budget.
            // The per-attempt slices already audited above; this is
            // the final state.
            AuditLogger.log(
                event: .audioUploadFailed,
                sessionId: captureSessionId,
                extra: [
                    "attempt": "\(uploadError.attempt)",
                    "error_category": uploadError.category.rawValue,
                    "terminal": "true",
                ]
            )
            handleUploadFailure(
                category: uploadError.category,
                sessionId: captureSessionId,
                isDemoFallback: false,
                specialty: captureSpecialty
            )
        } catch {
            // P0-03: NEVER fabricate clinical content in production. The demo
            // fallback is `#if DEBUG`-stripped so the call site doesn't even
            // exist in pilot/release binaries — `createDemoNote` is not in
            // scope outside Debug builds.
            #if DEBUG
            if DemoMode.isEnabled {
                // The DEBUG path was used by the in-Simulator demo flow
                // (no real mic). The new file-on-disk path means we don't
                // reach here for "no audio" — that's caught upstream as
                // PersistError.empty. This branch now only covers a
                // genuine post-upload failure (speaker tags failed, note
                // fetch failed, etc.) under DemoMode.
                self.error = "Transcription failed (demo): \(L("processing.stage1Failed.detail"))"
                stage1Status = .ready
                note = createDemoNote(sessionId: captureSessionId, specialty: captureSpecialty)
                uiState = .noteReady
                return
            }
            #endif
            // Any non-coordinator non-Stage1Wait error: fetchNote() /
            // applySpeakerTags / decoder failure. Surface generically;
            // the upload itself succeeded so retrying makes sense.
            self.error = L("processing.stage1Failed.detail")
            stage1Status = .failed(reason: L("processing.stage1Failed.detail"))
            AuditLogger.log(
                event: .stage1Failed,
                sessionId: captureSessionId,
                // `error.localizedDescription` can echo a request URL
                // (which carries the session id) — strip it before audit.
                // Per the lane's PHI-safety rule we send only a fixed-
                // shape reason here.
                extra: ["reason": "post_upload_processing_error"]
            )
            // Stay in uiState == .processing so the retry prompt remains reachable.
        }
    }

    // MARK: - Audio persistence (lane-ios/audio-upload-resilience)

    /// Result of writing the recorded audio to disk in preparation for
    /// upload. The URL is the file the AudioUploadCoordinator will read
    /// from on each attempt; `bytes` is what we put in the
    /// `recording_file_finalized` audit so backend dashboards can
    /// correlate audio size with upload latency.
    private struct PersistedAudio {
        let url: URL
        let bytes: Int64
        /// True iff this call wrote a NEW file (vs. reusing an existing
        /// one from a prior submitAudio attempt). Lets the caller emit
        /// `recording_file_finalized` exactly once per actual finalize
        /// — Retry doesn't re-emit since the bytes haven't been
        /// re-finalized.
        let wasFreshlyWritten: Bool
    }

    /// Failure modes for `persistRecordedAudioIfNeeded`. Distinct cases
    /// so `submitAudio` can route each to a different localized message
    /// + audit `reason` payload.
    private enum PersistError: Error {
        /// No PCM in the buffer AND no on-disk file from a previous
        /// attempt. Almost always a too-short recording.
        case empty
        /// PCM was present but couldn't land on disk (sandbox full,
        /// permission lost, etc.).
        case writeFailed
        /// Retry path: a file was expected (recordedAudioFileURL was
        /// non-nil) but vanished from disk. iOS sandbox cleanup or a
        /// force-quit + restart sequence. Terminal — no bytes to retry
        /// from.
        case recordingLost
    }

    /// Return the on-disk WAV that the upload chain should POST,
    /// writing one if we don't have one yet for this session.
    ///
    /// Branches:
    ///   * `recordedAudioFileURL` already points at a file on disk →
    ///     reuse it (retry path). Don't touch the audio source.
    ///   * `recordedAudioFileURL` was set but the file is gone →
    ///     throw `.recordingLost`. iOS sandbox cleanup OR an external
    ///     `clearRecordedAudioFile` call. Caller surfaces re-record.
    ///   * No URL set → pull the WAV out of the audio source. If the
    ///     buffer is empty, throw `.empty`. Otherwise write to disk
    ///     with `.completeFileProtection` (same protection class as
    ///     `OfflineUploadQueue` — raw clinical bytes never readable
    ///     while the device is locked).
    private func persistRecordedAudioIfNeeded(
        sessionId: String
    ) throws -> PersistedAudio {
        let fm = FileManager.default

        if let existing = recordedAudioFileURL {
            if fm.fileExists(atPath: existing.path) {
                let bytes = (try? fm.attributesOfItem(atPath: existing.path)[.size] as? Int64)
                    ?? Int64((try? Data(contentsOf: existing).count) ?? 0)
                return PersistedAudio(
                    url: existing,
                    bytes: bytes,
                    wasFreshlyWritten: false
                )
            }
            // Had a URL, file is gone — terminal for retry. Clear the
            // stale URL so a future startNewSession isn't fooled into
            // thinking there's still a file.
            recordedAudioFileURL = nil
            throw PersistError.recordingLost
        }

        // No file yet — pull bytes out of the audio source and write.
        let captured = audioSource.getRecordedAudioData()
        guard let bytes = captured, !bytes.isEmpty else {
            throw PersistError.empty
        }

        let directory = audioUploadStagingDirectory()
        do {
            try fm.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
        } catch {
            throw PersistError.writeFailed
        }

        // One file per session — collisions don't happen because
        // session ids are UUIDs, and a retry hits the existing-file
        // branch above. Filename matches OfflineUploadQueue's pattern
        // so a future "promote-to-offline-queue" path can adopt it.
        let url = directory.appendingPathComponent("\(sessionId).wav")
        do {
            try bytes.write(to: url, options: [.atomic, .completeFileProtection])
        } catch {
            throw PersistError.writeFailed
        }
        recordedAudioFileURL = url
        return PersistedAudio(
            url: url,
            bytes: Int64(bytes.count),
            wasFreshlyWritten: true
        )
    }

    /// Staging directory for the active upload's WAV. Lives under
    /// Application Support (not the OS temp dir) so a discretionary
    /// sandbox sweep doesn't yank the bytes between `submitAudio` and
    /// a Retry. Excluded from iCloud backup is the OfflineUploadQueue's
    /// responsibility, not ours — this directory holds only the
    /// currently-uploading session's WAV, which is short-lived.
    private func audioUploadStagingDirectory() -> URL {
        let fm = FileManager.default
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("AudioUploadStaging", isDirectory: true)
    }

    /// Delete the on-disk WAV from the upload-staging directory and
    /// clear the stored URL. Called on:
    ///   * successful upload (backend ACK'd the bytes), and
    ///   * session teardown / save-for-later (raw bytes shouldn't
    ///     outlive the session).
    private func clearRecordedAudioFile() {
        guard let url = recordedAudioFileURL else { return }
        try? FileManager.default.removeItem(at: url)
        recordedAudioFileURL = nil
    }

    /// Map an `AudioUploadErrorCategory` onto a localized user-facing
    /// string and an audit `reason`, surface to the UI, and (for
    /// network failures only) try the offline-queue fallback path.
    ///
    /// Pulled out so the `catch AudioUploadError` arm of `submitAudio`
    /// stays narrative. The `specialty` argument is only used by the
    /// offline-queue fallback (the queue stamps it for the sync banner).
    private func handleUploadFailure(
        category: AudioUploadErrorCategory,
        sessionId: String,
        isDemoFallback: Bool,
        specialty: String
    ) {
        // Network failures: try the offline queue first. If we can
        // park the WAV there, the encounter is safe and will sync on
        // reconnect — same UX as the pre-coordinator offline path.
        // (The submitProcessing pre-check already handles "known
        // offline at start"; this catches "went offline mid-upload"
        // and the coordinator's classified-as-network errors.)
        if category == .network {
            Task { @MainActor [weak self] in
                await self?.queueAudioOffline()
            }
            return
        }

        let detail: String
        switch category {
        case .fileMissing:
            // The on-disk WAV vanished between attempts. Terminal —
            // there's nothing left to retry from.
            detail = L("audio_upload_recording_lost")
            // Clear the (stale) URL so a clinician-driven Retry surfaces
            // the same `recording_lost` instead of a `file_missing`
            // loop.
            recordedAudioFileURL = nil
        case .server4xx:
            // 4xx is "bad request" — retrying the same bytes won't
            // help. Phrasing nudges the clinician toward "the bytes
            // are safe, but something on the server rejected this
            // request." Same copy as 5xx for the clinician (they
            // don't need to know which arm of the server rejected
            // it); the audit trail carries the granular category.
            detail = L("audio_upload_failed_server")
        case .server5xx:
            detail = L("audio_upload_failed_server")
        case .network:
            // Unreachable — guarded above.
            detail = L("audio_upload_failed_network")
        case .unknown:
            // Generic — use the server copy since "something went
            // wrong, the recording is safe" matches the user need.
            detail = L("audio_upload_failed_server")
        }

        self.error = detail
        stage1Status = .failed(reason: detail)
        // Stay in uiState == .processing so the retry prompt remains reachable.
        _ = isDemoFallback // reserved for a future demo-mode path
        _ = specialty
        _ = sessionId
    }

    // MARK: - Stage 1 wait helpers (Bug A)

    /// Wait for Stage 1 to actually land. RACES the WebSocket push against
    /// a `GET /notes/{id}/stage1` poll (#277). The push wins on the happy
    /// path (zero polling, no jitter); the poll backstops it whenever the
    /// socket is silent — connected-but-no-event, dropped, or never
    /// connected — which the old WS-failure-gated fallback could not cover
    /// (a healthy-but-silent socket hung the screen at 95% forever).
    ///
    /// **No wall-clock cap.** PR #245 originally shipped a 5-minute
    /// fallback deadline as a "safety net." That deadline was the same
    /// bug class as the original 30s wall — a slow LLM cold start or
    /// AssemblyAI queue spike on a legitimate recording would still
    /// false-fail. The deadline is removed entirely: the loop polls
    /// until either the note arrives or the surrounding Task is
    /// cancelled (user backs out of the processing screen, app is
    /// killed, etc.). The `try? await Task.sleep` already cooperates
    /// with cancellation; the explicit `Task.isCancelled` check exits
    /// the loop the moment a cancellation fires.
    ///
    /// Backend-side explicit `stage1_failed` events are surfaced through
    /// the WS subscriber's separate code path (when added) and would
    /// route to `.failed(reason:)` directly — never through this helper.
    ///
    /// Fallback path emits `stage1_ws_fallback_to_poll` so the audit
    /// trail records WHY the iOS client paid the polling tax — useful
    /// for sizing the WS infra post-pilot.
    private func awaitStage1Ready(
        subscription: Stage1WSSubscriber,
        sessionId: String
    ) async {
        // RACE the WS push against the REST poll — do NOT gate the poll on
        // WS failure (#277). The old sequential form (`if waitForReady
        // return; else poll`) hung forever when the socket was connected
        // but silent: `waitForReady()` never returned, so the poll never
        // started, and the screen held at 95%. The backend pipeline is
        // synchronous (the note exists by the time the upload returned
        // 2xx), so the poll resolves quickly as a backstop.
        //
        // First path to see the note wins; the loser is torn down. The
        // poll's 2s initial cadence doubles as the WS's head-start, so on
        // the happy path (push wired, #290) the WS wins before any poll GET
        // — no fallback audit, no extra request. Still no wall-clock cap:
        // both paths return only on the real note or Task cancellation
        // (preserves the PR #245 no-false-fail principle).
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { await subscription.waitForReady() }
            group.addTask { [weak self] in
                await self?.pollStage1UntilReady(sessionId: sessionId) ?? false
            }
            for await ready in group {
                if ready { break }
            }
            // CRITICAL: resolve the WS subscriber's CheckedContinuation
            // before the group drains. cancelAll() alone would leave the
            // suspended waitForReady() continuation unresolved → the child
            // never completes → withTaskGroup deadlocks. cancel() resumes
            // it (idempotent if the WS already fired); cancelAll() then
            // stops the losing poll's sleep.
            subscription.cancel()
            group.cancelAll()
        }
    }

    /// Unbounded 2s poll of `GET /notes/{id}/stage1`, used as the backstop
    /// in the `awaitStage1Ready` race. Returns `true` once the note lands,
    /// `false` only on Task cancellation. The 2s initial cadence gives the
    /// WebSocket push a head start; if the socket is silent this is what
    /// actually advances the screen. Emits `stage1_ws_fallback_to_poll`
    /// when the poll (not the WS) delivered — so the audit records why we
    /// paid the polling tax (and does NOT fire when the WS won, because the
    /// poll is cancelled mid-sleep before it ever reaches this line).
    private func pollStage1UntilReady(sessionId: String) async -> Bool {
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 2 * 1_000_000_000)
            if Task.isCancelled { return false }
            do {
                _ = try await api.getStage1Note(sessionId: sessionId)
                AuditLogger.logRaw(
                    eventType: "stage1_ws_fallback_to_poll",
                    sessionId: sessionId,
                    extra: [:]
                )
                return true
            } catch APIError.notFound {
                // Note not generated yet — keep polling.
                continue
            } catch {
                // Any other error — keep polling. A single network hiccup
                // shouldn't end the wait while the note may still land.
                continue
            }
        }
        return false
    }

    /// Flip `processingStatus` to a reassurance string after
    /// `AppConfig.stage1LongRunStatusFlipSeconds`. No state change —
    /// just UX copy that tells the clinician "still working, the app
    /// isn't frozen." Returns the task so the caller can cancel it on
    /// any exit path.
    private func scheduleStage1LongRunStatusFlip() -> Task<Void, Never>? {
        Task { [weak self] in
            let delay = UInt64(AppConfig.stage1LongRunStatusFlipSeconds * 1_000_000_000)
            try? await Task.sleep(nanoseconds: delay)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                guard let self else { return }
                // Only flip if we're still waiting — don't stomp a
                // .ready or .failed status that arrived first.
                switch self.stage1Status {
                case .uploading, .generating:
                    self.stage1Status = .stillWorkingLong
                    self.processingStatus = L("processing.stillWorkingLong")
                case .stillWorkingLong, .ready, .failed, .idle, .queuedOffline:
                    break
                }
            }
        }
    }

    /// Re-fire the Stage 1 pipeline after a timeout/failure. The on-
    /// disk WAV persists across the Stage 1 failure (cleared only on
    /// a successful backend ACK), so this re-runs the upload from the
    /// same bytes — Bug 2: previously Retry was a no-op against an
    /// upload that had never reached the backend in the first place,
    /// because the in-memory PCM accumulator had been wiped and there
    /// was no on-disk source to replay from.
    ///
    /// If the on-disk file ALSO vanished (force-quit + iOS sandbox
    /// sweep), `submitAudio` catches that via `PersistError.recordingLost`
    /// and surfaces the "Recording lost — please re-record" terminal
    /// state. We don't pre-check here because `submitAudio` owns the
    /// localized-message lookup; pre-checking would duplicate it.
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
        // Tear down the on-disk WAV used by the upload chain — if Stage 1
        // succeeded the file is already gone (clearRecordedAudioFile fired
        // after the 2xx); if the user is bailing mid-flight we don't want
        // raw clinical bytes lingering across "Save for later."
        clearRecordedAudioFile()
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
        // Also drop the on-disk WAV that the upload chain uses — the
        // PCM purge above only clears the in-memory accumulator, so
        // we'd otherwise leak the persisted bytes across purges.
        clearRecordedAudioFile()
        maskingFailedFrames = []
    }

    func endSession() {
        teardownLiveTranscriber()
        stopScreenCaptureIfRunning()
        // Belt-and-suspenders end of the Live Activity. `stopRecording`
        // already ends it on the normal path; covers the abort cases
        // (review dismissed, crash recovery discard, etc.).
        liveActivity.end()
        // Drop the on-disk WAV — same reasoning as `saveForLater`.
        clearRecordedAudioFile()
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
            participants: [],
            externalReferenceId: response.externalReferenceId,
            providerOverrides: response.providerOverrides
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

    // MARK: - Processing progress estimator

    /// uiState didSet hook — starts a smooth 0 → 0.95 animation over
    /// the Stage 1 SLA window when we enter ``.processing``, tears it
    /// down when we leave. The percentage is an estimate (the backend
    /// doesn't emit per-step events today), but it visibly moves so
    /// the physician knows the app is working instead of frozen.
    private func handleProcessingProgress(
        from oldState: SessionUIState, to newState: SessionUIState
    ) {
        if newState == .processing && oldState != .processing {
            startProcessingProgressAnimation()
        } else if newState != .processing && oldState == .processing {
            processingProgressTask?.cancel()
            processingProgressTask = nil
            processingProgress = 0.0
        }
    }

    private func startProcessingProgressAnimation() {
        processingProgressTask?.cancel()
        processingProgress = 0.0
        processingProgressTask = Task { [weak self] in
            // Stage 1 SLA is < 30s (CLAUDE.md). Climb 0 → 0.95 over
            // 25s in small steps so the ring moves continuously; the
            // last 5% (.95 → 1.0) is reserved for "actually done".
            // If the backend runs LONGER than 25s we hold at 0.95
            // rather than overshoot; the uiState transition off
            // .processing will then reset.
            let totalSteps = 50
            let stepSeconds: Double = 0.5
            for step in 1...totalSteps {
                try? await Task.sleep(
                    nanoseconds: UInt64(stepSeconds * 1_000_000_000)
                )
                if Task.isCancelled { return }
                let target = min(0.95, Double(step) / Double(totalSteps) * 0.95)
                await MainActor.run { [weak self] in
                    guard let self else { return }
                    withAnimation(.easeOut(duration: stepSeconds)) {
                        self.processingProgress = target
                    }
                }
            }
        }
    }
}
