# Plan — bg-task-retain: fire-and-forget background tasks must not be GC'd

## Task
bg-task-retain — web-portal video imports stall permanently at "Extracting
audio." The audit log shows EVERY import emits only `consent_attested` →
`video_import_started`, then nothing — no `stage1_started`, no state
transition, and **no `video_import_failed`**. The orchestrator body never runs.

## Why
Root cause: the orchestrators are dispatched with a **bare**
`asyncio.create_task(coro)` whose result is never stored —
`video_import.py:324` (`_run_video_import_in_background`) and
`notes.py:348` (`_run_stage2_in_background`). CPython keeps only a **weak**
reference to a Task; an un-referenced task can be garbage-collected before it
runs, and the coroutine then never executes (documented behavior — the
`asyncio.create_task` docs say to keep a reference). Under deployed load this
happens reliably → the job is left `pending`, no work happens, and no failure
is recorded.

This also explains why #570 (per-poll watchdog) and #571 (startup sweep) didn't
help: both only reap jobs in **`running`** state, but a dropped task never
reaches `mark_running`, so the job is stuck in **`pending`** — invisible to both.
The long-lived pollers (`appconfig`, `provider_overrides`, `detectors`, `emr`,
`scheduler`, `template_override_cache`) are unaffected — they each assign the
task to a module/instance variable, so the reference is retained.

Satisfies CLAUDE.md error-handling ("No broken session without an audit log
entry"; "App crash → recovery flow").

## Approach
1. `app/core/background.py` — `spawn_background_task(coro, *, name=None)`: create
   the task, hold a strong reference in a module-level set, and discard it via
   `add_done_callback`. The canonical fix for fire-and-forget tasks.
2. Replace the bare fire-and-forget sites with it: the two orchestrators
   (`video_import.py`, `notes.py`) and the two alert sinks (`slack_sink.py`,
   `email_sink.py` — same defect, best-effort notifications).
3. **Defense in depth**: mark the import job `running` in the route
   (`start_processing`) right before dispatch, and drop the now-redundant
   `mark_running` from the orchestrator. The job is `running` the moment
   `/process` returns, so even a future dropped/dead task is recoverable by the
   watchdog (#570) / startup sweep (#571), and a duplicate `/process` is
   correctly rejected (409 "already running").

## Acceptance criteria
- [ ] AC-1: `spawn_background_task` runs the coroutine and retains a strong reference until done (the task is in the live set while pending, removed after) — `tests/unit/test_background_tasks.py`.
- [ ] AC-2: `start_processing` marks the job `running` (committed) BEFORE dispatching, and dispatches via `spawn_background_task` — `tests/unit/test_video_import_process_dispatch.py`.
- [ ] AC-3: re-calling `/process` on an already-`running` job is rejected 409 — same test file.
- [ ] AC-4: full backend unit suite stays green.

## DRY / SOLID check
- **Existing helpers reused**: `jobs.mark_running`, `get_owned_session_or_404`,
  `write_audit`, `_status_response`. The new `spawn_background_task` REPLACES the
  bare-`create_task` pattern at all 4 fire-and-forget sites (removes duplication,
  not adds it) — the altitude fix (generalize the mechanism, don't patch one
  call site).
- **New helper**: `app/core/background.py::spawn_background_task` — one home for
  retained fire-and-forget scheduling.
- **OCP/DIP**: stdlib only; no provider/branch changes.

## Out of scope
- A full external queue / durable-execution worker (still the larger post-pilot
  change; this makes the in-process tasks reliable).
- Reaping stuck `pending` jobs (the route-side `mark_running` means new jobs are
  never stuck `pending`; existing stuck-`pending` rows are re-runnable via
  `/process` or can be cleared manually).
- Converting the long-lived pollers (already safe).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_background_tasks.py tests/unit/test_video_import_process_dispatch.py -q`
2. `cd backend && python3 -m pytest tests/unit -q`  → all pass
3. `curl -fs localhost:8080/health` → 200
4. N/A: iOS (no iOS change); docker rebuild (module/route change, unit-tested).

## Security implications
- No PHI: no new logging of patient data; audit `reason`/events unchanged + PHI-free.
- Audit append-only preserved. No new AI prompts, masking, consent, or secrets
  paths. The consent hard-gate in `start_processing` is unchanged (still checked
  before `mark_running` / dispatch).
