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
    /// Recorded offline — the audio is persisted to the on-device upload
    /// queue and will sync automatically on reconnect. Not an error; no retry
    /// prompt (ProcessingView shows a dedicated "saved offline" panel).
    case queuedOffline

    /// When non-nil, ProcessingView shows a retry prompt with this copy.
    var retryPrompt: (title: String, detail: String)? {
        switch self {
        case .timedOut(let elapsed):
            return ("Stage 1 timed out", "The note didn't generate within \(Int(elapsed))s.")
        case .failed(let reason):
            return ("Stage 1 failed", reason)
        case .idle, .uploading, .generating, .ready, .queuedOffline:
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
    /// once the WAV is safely on disk.
    private func queueAudioOffline() async {
        guard let session else { return }
        guard let audio = audioSource.getRecordedAudioData(), !audio.isEmpty else {
            // No captured audio (too-short recording). Nothing to queue —
            // surface the same guidance as the online path.
            self.error = "Recording was too short. Speak for at least a few seconds before stopping."
            stage1Status = .failed(reason: "Recording too short")
            return
        }
        do {
            try OfflineUploadQueue.shared.enqueue(
                sessionId: session.id,
                specialty: session.specialty,
                audio: audio
            )
            audioSource.discardRecordedAudio()
            stage1Status = .queuedOffline
            processingStatus = ""
            AuditLogger.log(
                event: .audioQueuedOffline,
                sessionId: session.id,
                extra: ["bytes": "\(audio.count)"]
            )
        } catch {
            self.error = "Couldn't save the encounter for later: \(error.localizedDescription)"
            stage1Status = .failed(reason: error.localizedDescription)
        }
    }

    // MARK: - Visual Evidence Submission (P1-5 dual-mode)

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
        let mode = pipeline.visualEvidenceMode
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
            if let token = KeychainHelper.shared.bearerToken() {
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }

            var builder = MultipartBuilder(boundary: boundary)
            builder.appendFile("audio_file", filename: "recording.wav", mime: "audio/wav", data: audioPayload)
            request.httpBody = builder.finish()

            stage1Status = .generating
            processingStatus = L("processing.generatingNote")
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
        } catch let urlError as URLError where Self.offlineURLErrorCodes.contains(urlError.code) {
            // Connectivity dropped mid-upload — persist for deferred sync
            // instead of failing. (submitProcessing already routes a known-
            // offline submit straight to the queue; this catches the race
            // where the network died after the request started.)
            await queueAudioOffline()
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
            participants: [],
            externalReferenceId: response.externalReferenceId
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
