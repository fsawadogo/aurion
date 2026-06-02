# P1-3 — POST /clips/{session_id} endpoint + Stage 2 dispatch

Plan reference: `/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`
(full dual-mode visual evidence plan — frames + clips with runtime
selection, sections "Backend changes → New endpoint" and "Vision service
routing").

P1-1 (merged) added the schema, audit events, AppConfig wiring, and the
abstract `caption_clip` method on `VisionProvider`. P1-2 (merged) lit up
real `caption_clip` implementations for Gemini (native) and
OpenAI/Anthropic (lossy midpoint-still fallback). P1-3 closes the
backend half: receive clips at the HTTP edge, store them KMS-encrypted,
audit the upload, dispatch them through the Stage 2 vision pipeline by
evidence kind, and extend the cleanup TTL to cover the clips path.

After this PR the backend can receive + process clips end-to-end.
iOS still sends nothing (lane-ios/p1-5 owns the iOS-side dispatcher
that decides frame vs clip per trigger and calls the new endpoint).

## Why

Today's `/api/v1/frames/{session_id}` accepts only static JPEG frames.
The dual-mode plan keeps frames as the default cheap/static evidence
type and adds clips as a parallel path for motion-heavy triggers (ROM,
gait, surgical technique, dressing-change technique). Without a clips
endpoint the iOS side has nowhere to ship the masked MP4 it now
produces in `MaskingPipeline.maskClip`. Without Stage 2 dispatch by
evidence kind, every uploaded clip would still be routed to
`caption_frame` and the native-video advantage of Gemini would be lost.

## Scope of this PR (P1-3)

Backend, additive only. Default `visual_evidence_mode=frames_only`
keeps every existing call site byte-identical.

- **`backend/app/api/v1/clips.py`** — new endpoint
  `POST /api/v1/clips/{session_id}` mirroring `frames.py` line-for-line
  on security model: owner assertion → fail-closed masking gate →
  content-type validation → KMS-encrypted S3 PutObject → audit emit →
  response. Accepts `video/mp4` (audio-stripped iOS-side per the plan's
  "audio track in clips" decision).

- **`backend/app/api/v1/_helpers.py`** — extract the
  `parse_masking_proof`-shaped clip-masking-metadata helper +
  the empty-body / content-type guard so frames.py and clips.py share
  the validation surface. DRY check: today frames.py + clips.py would
  share ~85% of the upload pipeline; the shared bits move into helpers.

- **`backend/app/modules/config/provider_registry.py`** — new
  `get_vision_provider_for_kind(kind)` method that reads
  `config.providers.vision` for `"frame"` and `config.providers.vision_clip`
  for `"clip"`. Both kinds keep their own fallback chains. Existing
  `get_vision_provider()` + `get_vision_provider_with_fallback()` stay
  unchanged for the frame path so today's call sites don't shift.

- **`backend/app/modules/vision/service.py`** — extend Stage 2 loop to
  branch once on `evidence_kind` and call either `caption_frame` or
  `caption_clip`. Low-confidence clips emit `CLIP_DISCARDED` (not
  `FRAME_DISCARDED`). The Stage 2 progress WebSocket event keeps
  working with the merged count.

- **`backend/app/modules/cleanup/service.py`** — extract a single
  `_purge_evidence_for_session(session_id, kind)` helper covering both
  the frames-only and clips-only and combined purge paths. The existing
  `purge_frames` keeps its signature for backward compat; a new
  `purge_clips` and combined `purge_all_evidence` parallel it. Same
  24h-post-Stage-2 TTL pattern. Same eval-tagged migration.

- **`backend/app/main.py`** + `backend/app/api/v1/__init__.py` — mount
  the new clips router.

- **Tests** —
  - `tests/integration/test_clips_endpoint.py` — happy path, fail-closed
    masking rejection, role gate, owner assertion, validation,
    content-type validation, PHI scan over log statements.
  - `tests/unit/test_vision_service_dispatch.py` — Stage 2 dispatch
    routes mixed frames + clips evidence to the right provider method;
    low-confidence clips emit `CLIP_DISCARDED`; registry routing
    by kind picks the correct provider.

## Acceptance criteria

- [ ] **AC-1** `POST /clips/{session_id}` with `masking_confirmed=true`,
      `Content-Type: multipart/form-data` carrying `video/mp4` body →
      `200`, response payload includes `clip_id`, `s3_key`,
      `evidence_kind="clip"`. Verified by
      `tests/integration/test_clips_endpoint.py::test_happy_path_clip_upload`.

- [ ] **AC-2** `POST /clips/{session_id}` with `masking_confirmed=false`
      → `400`, **NO** `PutObject` to S3, **NO** `clip_uploaded` audit
      event. Verified by
      `test_clips_endpoint.py::test_fail_closed_rejects_unmasked_clip`.

- [ ] **AC-3** `POST /clips/{session_id}` with the clip file's
      `Content-Type` set to `image/jpeg` → `400`. Verified by
      `test_clips_endpoint.py::test_content_type_validation_rejects_jpeg`.

- [ ] **AC-4** Owner assertion: a CLINICIAN posting to another
      clinician's session → `404` (clinician-to-clinician path hides
      existence per `_helpers.py:assert_owner`). Verified by
      `test_clips_endpoint.py::test_owner_assertion_blocks_cross_clinician`.

- [ ] **AC-5** Missing required form field (`timestamp_ms`, `duration_ms`,
      `trigger_segment_id`, `frames_total`, `frames_with_faces`,
      `masking_confirmed`) → `422` from FastAPI's validation. Verified by
      `test_clips_endpoint.py::test_missing_required_fields_returns_422`.

- [ ] **AC-6** `registry.get_vision_provider_for_kind("clip")` returns
      the `vision_clip` AppConfig provider; `("frame")` returns the
      `vision` provider. Verified by
      `tests/unit/test_vision_service_dispatch.py::test_registry_routes_by_kind`.

- [ ] **AC-7** Stage 2 dispatch with mixed evidence list (frames + clips)
      calls `caption_clip` for clip rows and `caption_frame` for frame
      rows. Verified by
      `test_vision_service_dispatch.py::test_stage2_dispatches_mixed_evidence`.

- [ ] **AC-8** Low-confidence clip caption emits `CLIP_DISCARDED` with
      the s3_key, confidence, and confidence_reason. Verified by
      `test_vision_service_dispatch.py::test_low_confidence_clip_emits_clip_discarded`.

- [ ] **AC-9** PHI scan over the new code: no `session_id` longer than
      8 chars in any log line, no clip bytes / transcript text in any log
      line. Verified by
      `test_vision_service_dispatch.py::test_no_phi_in_log_calls`.

## DRY / SOLID check

**Existing helpers to reuse** (grep-confirmed): `assert_owner`,
`get_owned_session_or_404`, `write_audit`, `parse_masking_proof`,
`get_s3_client`, `FRAMES_BUCKET`, `get_audit_log_service`, `get_registry`,
`with_retry`, `get_config`.

**New helpers introduced?** Two:

  1. `parse_clip_masking_proof()` in `_helpers.py` — third copy of the
     `MaskingProof` validation pattern would land in clips.py if not
     extracted; the second copy lives in frames.py. Threshold met.
  2. `get_vision_provider_for_kind(kind)` on `ProviderRegistry` — OCP:
     adding a new evidence kind in the future doesn't need a new method
     on the registry, just a new branch in the kind → config key map
     held in one dict.

**iOS UI tasks only — mobile-ios-design consulted**: n/a (backend).

## Out of scope

- iOS-side dispatcher (lane-ios/p1-5 territory).
- iOS reviewer's video player (lane-ios/p1-6 territory).
- New migration. P1-1 shipped the `frames` table with `evidence_kind`
  + `duration_ms`. This PR persists clip rows into the existing
  schema.
- Conflict-detection changes. Clips flow through the same
  `classify_conflicts` / `merge_visual_citations` path as frames; the
  output type `FrameCaption` is identical (Liskov per the provider
  abstraction).

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m pytest tests/integration/test_clips_endpoint.py tests/unit/test_vision_service_dispatch.py -v` — all new tests pass.
2. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m pytest -q` — full suite passes (baseline 732 from P1-2; ~750+ after P1-3).
3. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m ruff check .` — clean.
4. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m alembic upgrade head` — clean (no new migration; P1-1's 0023 still applies).
5. PHI scan: every `logger.*(...)` in `clips.py`, `cleanup/service.py`,
   `vision/service.py` logs at most the first 8 chars of `session_id`,
   never raw transcript text, never clip bytes.

## Security implications

- **Fail-closed masking (P0-01)**: the `masking_confirmed=false`
  rejection path is the FIRST gate after auth + owner assertion. No
  `PutObject` runs before that check. Test AC-2 locks this in.
- **No PHI in logs / errors / responses**: log call sites use the same
  8-char `session_id` truncation as frames.py; no clip bytes / transcript
  text / patient identifiers. Test AC-9 enforces.
- **AI calls via registry**: `caption_clip` is reached only through
  `registry.get_vision_provider_for_kind("clip")`. No direct provider
  instantiation in service.py.
- **Audit log append-only**: `clip_uploaded` and `clip_discarded` use
  `write_audit` → `AuditLogService.write_event` (DynamoDB PutItem, no
  UpdateItem/DeleteItem). No change to that contract.
- **KMS encryption**: S3 PutObject for clips uses the same
  `ServerSideEncryption="aws:kms"` pattern as frames (the bucket-level
  default policy in `infrastructure/s3.tf` already enforces this; the
  endpoint doesn't need to set the header explicitly but does so for
  defense-in-depth, matching frames.py).
- **Consent gate**: clips can only be uploaded to a session that's
  already past `CONSENT_PENDING` (covered by `get_owned_session_or_404`
  + the fact that no iOS client uploads until `RECORDING` →
  `PROCESSING_STAGE1`).
