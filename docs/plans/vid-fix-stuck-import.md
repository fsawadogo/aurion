# Plan — vid-fix-stuck-import: recover stuck video-import jobs

## Task
vid-fix-stuck-import — a web-portal video upload hangs forever on "Extracting audio"; the status poll spins indefinitely (and logs a benign 401).

## Why
Reported by the CPO. Root cause: processing runs as a fire-and-forget
`asyncio.create_task(_run_video_import_in_background(...))` (`video_import.py:324`).
If the worker recycles (redeploy/idle/crash) or audio extraction hangs, the task
dies before its `except → mark_failed`, leaving the job stuck in `running`. The
poll then returns a pre-Stage-1 status forever → infinite spinner. (The 401 is a
normal token-refresh blip — `fetchWithAuth` refreshes + retries.) Satisfies
CLAUDE.md error-handling: "No broken session without an audit log entry" /
"App crash → recovery flow on restart."

## Approach
Lazy watchdog + a poll give-up. No new infra (no cron / worker).
- `app/modules/video_import/jobs.py`: `fail_if_stale(db, job)` — if a job has
  been `running` past a budget (well beyond Stage 1 <30s / Stage 2 <5min SLAs),
  `mark_failed` it. Idempotent; no-op for non-running jobs.
- `app/api/v1/video_import.py`: a shared `_reap_stale_job(db, job, session_id)`
  helper that calls `fail_if_stale` and, when it flips the job, emits
  `VIDEO_IMPORT_FAILED` (mirroring the orchestrator). Both the clinician GET
  `/status` and the admin status route call it before serializing.
- `web/components/portal/VideoImportClient.tsx`: cap consecutive poll errors —
  the bare `catch { retry }` currently spins forever on a persistent 401 /
  network failure — and surface a terminal "lost contact" message. The existing
  `status === "failed"` branch already surfaces the watchdog-failed job.

## Acceptance criteria
- [ ] AC-1: a `running` job older than the budget is reported `failed` (not `running`) when `/status` is polled, and a `VIDEO_IMPORT_FAILED` audit is written — `tests/unit/test_video_import_watchdog.py`.
- [ ] AC-2: a `running` job within the budget is left `running` — same test file.
- [ ] AC-3: `fail_if_stale` is a no-op for non-running (pending/completed/failed) jobs — unit test.
- [ ] AC-4: the admin status route applies the same watchdog — unit test.
- [ ] AC-5: the web poll stops after N consecutive errors (`shouldStopPolling`) instead of spinning — `tests/VideoImportPoll.spec.tsx`.

## DRY / SOLID check
- **Existing helpers reused**: `jobs.mark_failed`, `jobs.get_job_for_session`,
  `utcnow` (`app.core.clock`), `write_audit`, `_status_response`,
  `AuditEventType.VIDEO_IMPORT_FAILED`. No new audit event.
- **New helper introduced?**: `jobs.fail_if_stale` (job-lifecycle logic in the
  jobs module — SRP) + `_reap_stale_job` (one API-layer helper called by BOTH
  status routes — prevents a 3rd copy). Route handlers stay HTTP-only.
- **OCP/DIP**: clock via `utcnow()`; no provider/branch changes.

## Out of scope
- Moving long pipeline work off fire-and-forget `asyncio.create_task` onto a
  durable worker/queue (the deep fix; also hardens Stage 2).
- An ffmpeg/extraction subprocess timeout.
- A startup recovery sweep for orphaned jobs (the lazy-on-poll watchdog covers
  the polled case the user hits).
- A web "Retry" button (the failed job is already re-runnable via `/process`).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_video_import_watchdog.py tests/unit/test_video_import_routes.py -q`
2. `cd web && npx vitest run tests/VideoImportPoll.spec.tsx tests/i18n-bootstrap.spec.ts`
3. `eslint` + `tsc --noEmit` clean on touched web files.
4. N/A this change: iOS builds (no iOS change); docker-stack boot (backend change is unit-tested at the route/service layer).

## Security implications
- No PHI: job rows + the audit `reason` carry no patient data (bounded, PHI-free string).
- Audit append-only preserved — uses `write_audit` (write_event); no update/delete.
- No new AI prompts, masking, consent, or secrets paths. The watchdog only flips a job status + audits.
