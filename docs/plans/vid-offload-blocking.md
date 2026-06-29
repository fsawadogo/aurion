# Plan — vid-offload-blocking: keep the import pipeline off the event loop

## Task
vid-offload-blocking — a web-portal encounter-video upload stalls at "Extracting
audio," and the status poll fails with a browser CORS / `net::ERR_FAILED` error
(observed live on `portal.aurionclinical.com` → `api-dev.aurionclinical.com`).

## Why
Reported by the CPO. Root cause: the video-import orchestrator
(`_run_video_import_in_background`, a fire-and-forget `asyncio.create_task`) runs
**synchronous, blocking work directly on the API event loop**:
- `client.download_file(...)` — the entire raw video, synchronous boto3
  (`video_import.py:681`).
- per-frame `mask_frame(...)` (OpenCV, CPU-bound) + `s3.put_object(...)`
  (`_extract_and_mask_frames`, `video_import.py:541/553`).
- `with_retry` does NOT offload — it calls its fn synchronously (`retry.py:72`).

A large download blocks the single event loop for seconds → uvicorn cannot
serve concurrent requests (the status poll) → the ALB returns a gateway
502/504 with no CORS headers → the browser reports "No Access-Control-Allow-Origin"
+ `ERR_FAILED`. (The app's own 500s keep CORS via the handler at `main.py:104`,
so a missing-ACAO response proves the failure was gateway-level — an
unresponsive worker, i.e. a blocked loop.) Sustained blocking can also fail the
container health check → ECS recycles the task → the in-process `except` never
runs → the job is stranded `running` ("Extracting audio" forever).
ffmpeg is already safe (subprocess + `ffmpeg_timeout`, `extraction.py:61`).

Satisfies CLAUDE.md error-handling ("App crash → recovery flow"; "No broken
session without an audit log entry") and the Stage-1/Stage-2 latency SLAs (the
hot path must not be blocked by another session's import).

## Approach
No new infra (no external queue/worker). Two moves:
1. **Offload the blocking work** off the event loop with `asyncio.to_thread`:
   - `_download_to_path(client, key, dest)` — raw-video download in a thread.
   - `_mask_and_store_frame(s3, session_id, ts_ms, jpg_bytes, drop_zero)` — a
     sync unit (mask + S3 put) run via `to_thread`; the async audit stays on the
     loop. OpenCV + boto3 release the GIL, so the loop stays responsive.
2. **Startup orphan recovery** — `jobs.recover_orphaned_jobs(db)` reaps jobs
   stranded `running` past the budget (reuses `fail_if_stale`), and an
   API-layer `recover_stuck_imports_on_startup()` audits each reaped session
   (`VIDEO_IMPORT_FAILED`) and is called from the lifespan startup. Budget-gated,
   so a job legitimately running on another live replica (< budget) is untouched.
   Complements the per-poll watchdog (#570): a job is now reaped on the next
   restart even when the poll itself can't reach a healthy worker.

## Acceptance criteria
- [ ] AC-1: the raw-video download runs off the event loop via `asyncio.to_thread` — `tests/unit/test_video_import_offload.py::test_download_offloaded`.
- [ ] AC-2: per-frame masking + S3 store run off the event loop; `_mask_and_store_frame` masks then stores on success and skips the store on a drop — `test_video_import_offload.py`.
- [ ] AC-3: `recover_orphaned_jobs` fails a stale `running` job and returns its session id; leaves a fresh `running` / non-running job untouched — `tests/unit/test_video_import_startup_recovery.py`.
- [ ] AC-4: `recover_stuck_imports_on_startup` writes a `VIDEO_IMPORT_FAILED` audit per reaped session — same test file.
- [ ] AC-5: full backend unit suite stays green.

## DRY / SOLID check
- **Existing helpers reused**: `jobs.fail_if_stale` + `STALE_RUNNING_BUDGET_S`
  (#570), `jobs.mark_failed`, `write_audit`, `mask_frame`, `MaskingProof`,
  `get_s3_client`, `utcnow`, `async_session_factory`. `asyncio.to_thread` is the
  same offload idiom already used in `email_sender.py:188` / `kms_encryption.py`.
- **New helpers**: `_download_to_path`, `_mask_and_store_frame` (SRP: one
  blocking unit each, so the loop offload is testable), `recover_orphaned_jobs`
  (job-state, audit-free — mirrors `fail_if_stale`'s split), and the API-layer
  `recover_stuck_imports_on_startup` (owns the audit, like `_reap_stale_job`).
- **OCP/DIP**: no provider branching; clock via `utcnow()`, audit via the
  existing helper.

## Out of scope
- A full external queue / durable-execution worker (Celery / Arq / SQS + a
  separate worker container). The offload + recovery fixes the symptom without
  new infra; the queue is the larger post-pilot change.
- Making `with_retry` itself offload sync callables (systemic; broader blast
  radius across every S3 call site).
- boto3 client connect/read timeouts in `get_s3_client` (global S3 behavior).
- A whole-orchestrator wall-clock `wait_for` (a `to_thread` can't be cancelled,
  so it wouldn't cleanly bound a hung thread; the watchdog + startup sweep bound
  the stranded-job window instead).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_video_import_offload.py tests/unit/test_video_import_startup_recovery.py tests/unit/test_video_import_watchdog.py -q`
2. `cd backend && python3 -m pytest tests/unit -q`  → all pass
3. `curl -fs localhost:8080/health` → 200 (stack already up)
4. N/A this change: iOS builds (no iOS change); docker rebuild (route/module change is unit-tested).

## Security implications
- No PHI: audit `reason` strings are bounded + PHI-free; no transcript/video
  content is logged. Masking semantics are unchanged — `mask_frame` still runs
  and the `MaskingProof` success invariant is still asserted before any S3 store;
  offloading only moves the same call into a worker thread (fail-closed
  preserved: a drop still skips the store).
- Audit append-only preserved (`write_audit` / `write_event`); no update/delete.
- No new AI prompts, consent paths, or secrets. Consent hard-gate untouched.
