# Plan — VID-06

## Task
Stage 2 auto-advance + admin/eval `/admin/video-imports` endpoints.

## Why
Deferred from VID-02/05. Lets the eval team process recorded test encounters
(attributed to a clinician, auto-advancing Stage 2 to a full multimodal note)
and gives clinician imports the same pipeline without auto-advance.

## Approach
- `api/v1/video_import.py`: factor `create_import_session(...)` and
  `start_processing(...)` shared helpers; `create_video_import` (clinician)
  delegates with `auto_advance_stage2=False`. Orchestrator: after masking +
  purge, if `job.auto_advance_stage2`, `_auto_advance_stage2` approves Stage 1
  + runs `run_stage2_vision` inline, leaving the session in PROCESSING_STAGE2
  (final approval + CONFLICTS stay human).
- `api/v1/admin/video_import.py` (new): create/process/status under
  `require_role(ADMIN, EVAL_TEAM)`, `on_behalf_of_clinician_id`,
  `auto_advance_stage2=True` default. Registered in `admin/__init__.py`.

Reuses: `approve_note`/`get_latest_note`/`run_stage2_vision`, `create_session`/
`confirm_consent`/`transition_session`, `get_session_or_404`, `jobs.*`.

## Acceptance criteria
- [ ] Orchestrator runs `_auto_advance_stage2` iff the job flag is set (unit-tested both ways).
- [ ] Admin create rejects missing consent (400); uses `on_behalf_of_clinician_id` + `auto_advance_stage2=True` (unit-tested).
- [ ] All routes 404 when the flag is off; full unit suite green.

## Out of scope
Web admin route (VID-09), multipart (VID-10), DNN detector (VID-07), infra (VID-08).

## Test plan
1. `python3 -m pytest tests/unit/test_video_import_*.py -q`
2. `python3 -c "import app.main"`

## Security implications
Auto-advance never auto-approves to REVIEW_COMPLETE — final approval +
conflict resolution stay human. Admin surface role-gated; consent hard-gate +
attestation preserved. Still dark behind `video_import_enabled`.
