# P1-5: maskClip + visual evidence dispatcher + uploadClip (iOS lane)

## Source plan

This PR implements step **P1-5** of the dual-mode visual evidence plan.

- Master plan: `/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`
- Phase: 1 (infrastructure, zero default behavior change)
- Default AppConfig mode stays `frames_only` after this PR ships, so no
  existing call site changes behavior unless the eval team explicitly
  flips `visual_evidence_mode` per-session.

## What this PR delivers

iOS-only, additive, default-frames-only:

1. **`Masking/MaskingPipeline.swift`** (extended) — adds
   `maskClip(_ inputURL: URL, sessionId: String) async -> MaskingResult`
   that streams raw frames from an input video-only MP4 via
   `AVAssetReader`, runs Apple Vision face detection on every frame, blurs
   each detected face via Core Image, and re-encodes a NEW MP4 via
   `AVAssetWriter` (H.264 main profile, **no audio track**). Fail-closed:
   any per-frame face-detect or writer failure aborts the WHOLE clip and
   returns `.failure(...)` — the masked file is deleted before the call
   returns, so no partial bytes ever reach the caller.
   - Extracted shared private helper `detectFacesAndBuildBlurredImage(_:)`
     used by BOTH `maskVideoFrame` AND `maskClip` so the per-frame
     face-detect-and-composite logic is defined exactly once (DRY §6c).
   - `MaskingResult` extended with optional clip-level metadata
     (`maskedFileURL`, `framesTotal`, `framesWithFaces`, `framesFailed`)
     while keeping the existing `imageData` path byte-identical.
   - Emits the existing `masking_confirmed` audit event with
     `frame_type=clip` + frame counts; emits `masking_failed` with the
     fail-closed frame index. No new audit event types — clip masking
     reuses the existing taxonomy, with `frame_type` discriminating.
   - Performance target: <500 ms per 7s clip @ 30fps on A15+ documented
     in a code comment.

2. **`Network/APIClient.swift`** (extended) — adds
   `uploadClip(sessionId:clipFileURL:timestampMs:durationMs:triggerSegmentId:framesTotal:framesWithFaces:)`
   that POSTs to `/api/v1/clips/{session_id}` via
   `URLSession.uploadTask(with:fromFile:)` so the multi-MB MP4 body never
   sits in RAM. Same `MultipartBuilder` boundary + bearer auth +
   masking-proof field set as `uploadFrame`.
   - Refactored `MultipartBuilder` to also produce a multipart-suffix
     `Data` blob that can be written to a streamable temp file alongside
     the raw MP4 body — the upload-from-file path needs the prefix
     (boundary + form fields) and suffix (closing boundary) flanking the
     file content in a single on-disk body. Helper `buildMultipartBodyFile(
     prefix:fileURL:suffix:)` writes them once to a temp file and returns
     its URL; `uploadClip` deletes the temp body file after the upload
     completes.

3. **`Session/SessionManager.swift`** (extended) — adds
   `extractEvidence(for trigger: TriggerEvent) async throws -> VisualEvidence`
   that consults `RemoteConfig.shared.pipeline.visualEvidenceMode` and
   dispatches:
   - `.framesOnly` → `.frame(currentFrame(at: trigger.timestamp))`
   - `.clipsOnly` → `.clip(extracted MP4 URL, duration, trigger)`
   - `.hybrid` → routes on `RemoteConfig.shared.pipeline.clipTriggerKinds`
     containment per trigger.kind.
   Renames `submitFrames` → `submitVisualEvidence` and rewrites its body
   to iterate over the captured frame list + any pending clip triggers,
   dispatching each through `extractEvidence` → masking → upload. Frame
   path is byte-identical; clip path is new but only fires when AppConfig
   flips to `clips_only` or `hybrid` (default stays `frames_only`).
   - `FailedMaskingFrame` widens its `kind` enum to include `.clip` and
     gains an associated `clipTrigger: TriggerEvent?` so the retry UI can
     surface which clip failed without holding the entire JPEG payload
     (clips don't have a `CapturedFrame` — the source bytes live in the
     ring buffer's masked output file).

4. **`Network/RemoteConfig.swift`** (extended) — `ClientPipelineResponse`
   gains optional `visualEvidenceMode: VisualEvidenceMode`,
   `clipWindowMs: Int`, `clipTriggerKinds: [String]` fields. All three
   default to safe values that preserve today's behavior
   (`.framesOnly`, `7000`, `["motion","rom","gait","procedural"]`) so a
   backend that doesn't yet emit them produces the same iOS behavior as
   today.

5. **`AurionTests/ClipDispatcherTests.swift`** (new) — covers:
   - `extractEvidence(for:)` returns `.frame` in `.framesOnly` mode.
   - `extractEvidence(for:)` returns `.clip` in `.clipsOnly` mode with
     the right duration window.
   - `extractEvidence(for:)` in `.hybrid` mode routes by trigger kind
     (motion → clip, clinic → frame).
   - `MaskingPipeline.maskClip` happy path: produces output MP4 with no
     audio track and `framesTotal > 0`.
   - `MaskingPipeline.maskClip` fail-closed: simulated invalid input MP4
     URL → `.failure`, no output file written.
   - `APIClient.uploadClip` builds the correct multipart body and uses
     `uploadTask(with:fromFile:)` rather than `Data(contentsOf:)`
     (verified by intercepting via a protocol-based fake URLSession that
     records which upload method was called).

## Acceptance criteria

- [ ] **AC-1**: `maskClip` on a valid video-only MP4 returns
  `MaskingResult` with `success == true`, `maskedFileURL != nil`,
  `framesTotal > 0`, `framesFailed == 0`, and the output MP4 has zero
  audio tracks. Verified by `ClipDispatcherTests.maskClip_happyPath_*`.
- [ ] **AC-2**: `maskClip` on an unreadable URL returns
  `MaskingResult.success == false` with `failureReason == .renderError`
  and `maskedFileURL == nil`. Verified by
  `ClipDispatcherTests.maskClip_failClosed_*`.
- [ ] **AC-3**: `extractEvidence` in `.framesOnly` returns `.frame(...)`
  regardless of trigger kind. Verified by
  `ClipDispatcherTests.extractEvidence_framesOnly_*`.
- [ ] **AC-4**: `extractEvidence` in `.clipsOnly` returns `.clip(...)`
  with the configured window duration. Verified by
  `ClipDispatcherTests.extractEvidence_clipsOnly_*`.
- [ ] **AC-5**: `extractEvidence` in `.hybrid` routes by trigger kind
  (clip when kind in clipTriggerKinds, frame otherwise). Verified by
  `ClipDispatcherTests.extractEvidence_hybrid_*`.
- [ ] **AC-6**: `APIClient.uploadClip` constructs a multipart body with
  fields `timestamp_ms`, `duration_ms`, `trigger_segment_id`,
  `frames_total`, `frames_with_faces`, `masking_confirmed=true`, and the
  `clip` file field with MIME `video/mp4`. Uses
  `URLSession.uploadTask(with:fromFile:)` (NOT `Data(contentsOf:)`).
  Verified by `ClipDispatcherTests.uploadClip_*`.
- [ ] **AC-7**: `xcodebuild` on iPhone 17 AND iPad Pro 11-inch (M4) both
  succeed.
- [ ] **AC-8**: Existing `AurionTests` continue to pass — no regression
  in `maskVideoFrame`, `redactScreenCapture`, ring buffer, or PHI pattern
  tests.

## DRY / SOLID check

- **Existing helpers reused**:
  - `MaskingPipeline.shared` (singleton), `applyFaceBlur(...)` core blur
    primitive, the `detectFaces` Vision wrapper.
  - `MultipartBuilder` for the multipart body (frame and clip share it).
  - `makeMultipartUpload(url:)` for request scaffolding (frame and clip
    share it).
  - `MaskingResult` (extended additively, all existing fields keep their
    semantics — `imageData`, `success`, `failureReason`, etc.).
  - `VisualEvidence` enum + `TriggerEvent` from P1-4 (consumed unchanged).
  - `VideoRingBuffer.extract(around:duration:)` from P1-4 (consumed
    unchanged for the `.clipsOnly` / `.hybrid` paths).
  - `RemoteConfig.shared.pipeline.*` (extended additively).
  - `AuditLogger` + the existing `masking_confirmed` / `masking_failed`
    event types — clip frames piggyback via `frame_type=clip`.
- **New helpers introduced**:
  - `MaskingPipeline.detectFacesAndBuildBlurredImage(_:)` — the per-frame
    "detect faces + composite blur over each face rect" helper used by
    BOTH `maskVideoFrame` AND `maskClip`. This is the third copy
    extracting from the existing inline path in `maskVideoFrame` plus
    the new clip path; the per-frame fan-out logic is defined exactly
    once (DRY §6c).
  - `VisualEvidenceMode` enum mirroring the backend `VisualEvidenceMode`
    enum (`framesOnly`, `clipsOnly`, `hybrid`). Single switch in
    `extractEvidence` — no scattered branches downstream (OCP §6c).
- **SRP**: MaskingPipeline owns masking; SessionManager owns
  orchestration (extracts evidence, dispatches to mask, dispatches to
  upload); APIClient owns HTTP. None of them know about the others'
  internals.
- **OCP**: `extractEvidence` switches once on `VisualEvidenceMode`.
  Adding a fourth mode in the future means extending the enum + one
  case in `extractEvidence`, not a chain of `if mode == X` across the
  module.
- **LSP**: `VisualEvidence.frame` and `.clip` have the same downstream
  contract — each gets handed to `MaskingPipeline.mask(_:sessionId:)`,
  each gets handed to APIClient upload — the dispatcher doesn't care
  which variant it's handling once it's been built.
- **DIP**: SessionManager doesn't construct `AVAssetWriter` or
  `VNDetectFaceRectanglesRequest` directly; those stay inside
  `MaskingPipeline`. `RemoteConfig.shared` is the injection point for
  runtime config — tests stub `VisualEvidenceMode` resolution via a
  pure helper that takes a value rather than reading the singleton.
- **iOS UI consulted (`mobile-ios-design`)**: n/a — this PR has no UI
  surface.

## Security implications

- **Fail-closed masking (P0-01)** is the non-negotiable invariant: any
  frame's face-detect failure OR any writer failure during `maskClip`
  aborts the WHOLE clip — output file deleted, `.failure` returned,
  caller never sees a partial MP4. The clip never reaches `uploadClip`
  in any failure branch.
- **Raw video frames never leave iOS unmasked**: `VideoRingBuffer.extract`
  produces a RAW MP4 in the temp directory. `maskClip` consumes that raw
  file → writes a NEW masked MP4 → returns the masked URL. Only the
  masked URL is handed to `uploadClip`. The dispatcher deletes the raw
  input file after `maskClip` returns (success or failure) so no raw
  bytes linger on disk.
- **Audio**: clips are video-only by contract. `maskClip` explicitly
  adds NO audio input to its `AVAssetWriter` even if the input MP4
  somehow had an audio track. Test `maskClip_outputHasNoAudio` asserts
  this.
- **No PHI in logs**: audit events carry frame counts only, never
  visual content.
- **iOS Keychain**: not touched.
- **Provider keys**: not relevant — `uploadClip` is the same backend
  endpoint, AI provider keys never come near iOS.

## Out of scope

- AppConfig wiring on the backend that emits the new
  `visual_evidence_mode` / `clip_window_ms` / `clip_trigger_kinds` keys
  via GET /config — the iOS client decodes them as optional with safe
  defaults so this PR is forward-compatible without needing a backend
  change first. The backend `ClientPipelineResponse` extension lands in
  a follow-up backend PR.
- Reviewer UI for clip evidence (P1-6, parallel worktree).
- Per-session override flag for `visual_evidence_mode` (eval team) —
  Phase 2 of the master plan.
- Provider abstraction for clip captioning (already shipped in P1-2).
- Backend `POST /clips/{session_id}` endpoint (already shipped in P1-3).
