# Plan — VID-01

## Task
VID-01 — Backend video-import foundation (audio-only, dark behind a flag).

## Why
First slice of the web-portal "upload an encounter video → same AI pipeline →
final note" feature (design: `~/.claude/plans/clever-drifting-boot.md`). Per
`AURION-CODING-WORKFLOW.md` §4/§16, large multi-surface features ship as thin
sequential slices. This slice lands the pure-additive scaffolding with **zero
behaviour change to the live pilot path** and **no new PHI surface** (no frame
extraction, no masking, no wired endpoints yet): a feature flag, audit events,
the job model + migration, the ffmpeg audio-extraction utility, an S3
raw-video bucket handle, and a raw-video purge helper. CLAUDE.md "Audio is the
spine" — audio extraction alone can drive Stage 1.

## Approach
Additive only. Files:
- `app/modules/config/schema.py` — `FeatureFlagsConfig.video_import_enabled = False` (master kill-switch; mirrors `measurement_enabled` dark-default posture).
- `app/core/audit_events.py` — new events `VIDEO_IMPORT_STARTED/COMPLETE/FAILED`, `CONSENT_ATTESTED`, `RAW_VIDEO_PURGED` + `ALLOWED_AUDIT_KWARGS` entries; update locked map in `tests/unit/test_audit_events.py`.
- `app/core/models.py` — `VideoImportJobModel` (mirrors `Stage2JobModel` + raw-video/frame-count fields) and additive nullable `SessionModel.import_source`.
- `alembic/versions/..._0041_video_import.py` — create `video_import_jobs` + add `sessions.import_source`.
- `app/core/s3.py` — `VIDEO_IMPORTS_BUCKET` constant (presigned PUT already supported by `generate_presigned_evidence_url(client_method="put_object", bucket=...)`).
- `app/modules/video_import/{__init__,errors,extraction,jobs}.py` — ffmpeg audio extraction (shell out via `asyncio.create_subprocess_exec`), job CRUD, typed errors.
- `app/modules/cleanup/service.py` — `purge_raw_video(session_id, s3_key)` mirroring `purge_audio` (success → `RAW_VIDEO_PURGED`, failure → existing `CLEANUP_PARTIAL_FAILURE`).

Reuses: `with_retry`, `get_s3_client`, `get_audit_log_service`, `utcnow`, the
`Stage2JobModel` job pattern, `purge_audio` structure. No new helper duplicates
an existing one (DRY §6c).

## Acceptance criteria
- [ ] AC-1: `video_import_enabled` defaults `False` — `pytest tests/unit/test_video_import_config_flag.py`.
- [ ] AC-2: `extract_audio` produces a non-empty WAV from an mp4 with an audio track, and raises `VideoExtractionError` on a non-video input — `pytest tests/unit/test_video_import_extraction.py`.
- [ ] AC-3: job CRUD lifecycle pending→running→completed/failed persists — `pytest tests/unit/test_video_import_jobs.py`.
- [ ] AC-4: `purge_raw_video` deletes the object + writes `RAW_VIDEO_PURGED`; failure writes `CLEANUP_PARTIAL_FAILURE` — `pytest tests/integration/test_video_import_purge.py`.
- [ ] AC-5: audit-event locked map + kwargs whitelist updated — `pytest tests/unit/test_audit_events.py`.

## DRY / SOLID check
- **Existing helpers reused**: `with_retry`, `get_s3_client`, `get_audit_log_service`, `utcnow`, `Stage2JobModel` shape, `purge_audio` pattern, `generate_presigned_evidence_url`.
- **New helper introduced?**: `extract_audio` (genuinely new boundary — ffmpeg), `purge_raw_video` (third purge sibling; matches `purge_audio` exactly), `VideoImportJobModel` (new entity). No duplicate of an existing pattern.
- **iOS UI**: n/a (backend).

## Out of scope
Orchestrator, `run_stage1` hot-path refactor, API endpoints, frame extraction,
**server-side masking** (compliance-gated, VID-04), Terraform bucket/CORS/KMS,
web portal. None of this slice is reachable at runtime (no router wired).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_video_import_extraction.py tests/unit/test_video_import_jobs.py tests/unit/test_video_import_config_flag.py tests/unit/test_audit_events.py -q`
2. `cd backend && python3 -m pytest tests/integration/test_video_import_purge.py -q`
3. `cd backend && python3 -c "import app.main"` (import-clean; app still boots)

## Security implications
No PHI surface added: no frames, no masking, no patient media reaches a vision
provider in this slice. Raw-video bucket handle added but nothing uploads to it
yet. Audit events are PHI-free (UUIDs/counts/bucket only). Flag defaults off.
