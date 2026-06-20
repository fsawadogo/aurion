# Plan — VID-02

## Task
VID-02 — Audio-only video-import working end-to-end: `run_stage1` refactor +
background orchestrator + clinician endpoints (behind `video_import_enabled`).

## Why
Builds on VID-01. Makes an uploaded encounter video produce a Stage 1 note
through the SAME pipeline iOS uses, reviewable in the portal — audio spine only
(frames/masking are VID-03/04). CLAUDE.md "Audio is the spine".

## Approach
- **Refactor (hot path, byte-identical)**: extract the Stage-1 body of
  `app/api/v1/transcription.py::submit_transcription` into a module-level
  `run_stage1(db, session, audio_bytes) -> Transcript` in the same file. The
  route becomes a thin wrapper (get_owned_session → require_state → read file →
  run_stage1 → response). Both the HTTP route and the import orchestrator call
  identical code (DRY). All deps already imported in transcription.py.
- **Orchestrator** beside the router (mirrors `notes.py::_run_stage2_in_background`):
  `app/api/v1/video_import.py::_run_video_import_in_background(session_id, job_id)`
  — own DB session via `async_session_factory()`; download raw video from
  `VIDEO_IMPORTS_BUCKET` to a `TemporaryDirectory`; `extract_audio`; drive
  CONSENT_PENDING(consent_confirmed)→RECORDING→PROCESSING_STAGE1; `run_stage1`
  (→ AWAITING_REVIEW); `purge_raw_video` + `mark_raw_video_purged`;
  `mark_completed` + `VIDEO_IMPORT_COMPLETE`. Failure → `mark_failed` +
  `VIDEO_IMPORT_FAILED` + CRITICAL alert (mirrors Stage 2).
- **Endpoints** (clinician, `/api/v1/me/video-imports`, all 404 when flag off):
  - `POST ""` → create session (`import_source="video_upload"`), apply consent
    attestation (`confirm_consent` + `CONSENT_ATTESTED`), return
    `{session_id, upload_url (presigned PUT to VIDEO_IMPORTS_BUCKET), s3_key}`.
  - `POST /{id}/process` → HEAD the raw video object (fail-closed if absent),
    `create_job`, `VIDEO_IMPORT_STARTED`, dispatch background task.
  - `GET /{id}/status` → job status + counts + session state.
- Register router in `app/main.py`.

Reuses: `run_stage1` (new shared seam), `extract_audio`/`jobs`/`purge_raw_video`
(VID-01), `get_owned_session_or_404`/`require_state`/`write_audit`,
`create_session`/`confirm_consent`/`transition_session`,
`generate_presigned_evidence_url(client_method="put_object")`,
`async_session_factory`, `get_config`.

## Acceptance criteria
- [ ] AC-1: endpoints 404 when `video_import_enabled=False` — `pytest tests/integration/test_video_import_endpoints.py`.
- [ ] AC-2: with flag on, `POST ""` creates a CONSENT_PENDING import session with `consent_confirmed=True` + emits `CONSENT_ATTESTED`, returns a presigned PUT url.
- [ ] AC-3: end-to-end — PUT a fixture video to S3 → `process` → poll status to `completed`; session reaches `AWAITING_REVIEW` with a Stage 1 note; raw video purged (`RAW_VIDEO_PURGED`, `video-imports/{sid}/` empty).
- [ ] AC-4: `run_stage1` refactor is behaviour-preserving — existing transcription tests still pass + a parity test asserts the route still returns the same `TranscriptResponse` shape.
- [ ] AC-5: `process` fails closed (404/409) when the raw video object is absent.

## DRY / SOLID check
- **Reuse**: `run_stage1` is the extracted shared seam (route + orchestrator);
  `_run_video_import_in_background` mirrors `_run_stage2_in_background`; VID-01
  helpers reused. No new copy of an existing pattern.
- **SRP**: route = HTTP boundary; `run_stage1` = pipeline; orchestrator = job
  sequencing.
- **OCP/DIP**: providers via registry (unchanged); S3/audit/clock via injected helpers.

## Out of scope
Admin/eval endpoints (next slice), frame extraction + masking (VID-03/04),
Stage 2 auto-advance, web UI, presigned **multipart** (single PUT here).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_transcription*.py -q` (refactor parity)
2. `cd backend && python3 -m pytest tests/integration/test_video_import_endpoints.py -q`
3. `cd backend && python3 -c "import app.main"`

## Security implications
No new PHI-to-vision surface (audio only). Raw video transiently in S3, purged
immediately post-extraction with audit proof. Consent hard-gate preserved via
attestation (`CONSENT_ATTESTED`). All endpoints 404 while the flag is off.
Masking path still absent (VID-04).
