# Plan — stage1-failed-enum: add STAGE1_FAILED to the session_state PG enum

## Task
stage1-failed-enum — a generic Stage-1 failure (e.g. the note-gen provider
returns unparseable JSON) crashes the failure handler instead of recording a
clean failure, stranding the session + job.

## Why
Found in CloudWatch (`/aurion/dev/api`) diagnosing the stuck video imports:
```
Gemini response parse failed: Unterminated string ... line 351
Video import failed: session=9a9f6cf1...
ERROR: invalid input value for enum session_state: "STAGE1_FAILED"
  [SQL: UPDATE sessions SET state=$1::session_state ...]  -> PendingRollbackError
```
`SessionState.STAGE1_FAILED` exists in the Python enum (`app/core/types.py:414`)
and the generic Stage-1-failure path transitions to it
(`app/api/v1/transcription.py:201`, `modules/session/service.py`), but the value
was **never added to the Postgres `session_state` enum** — the 2026-06-05 work
added only `STAGE1_FAILED_NO_AUDIO` (baseline list + migration 0030). So any
generic Stage-1 failure (provider parse error, rate limit, timeout) hits
`InvalidTextRepresentationError`, poisons the transaction (`mark_failed` then
also fails), and leaves the session/job stranded.

The baseline list is contractually "kept in lockstep with `SessionState`" —
see `tests/integration/test_migrations.py::test_baseline_enums_match_python_enums`
— which this restores. Satisfies CLAUDE.md error-handling: "No broken session
without an audit log entry."

## Approach
Mirror exactly what 0030 did for `STAGE1_FAILED_NO_AUDIO`:
1. Add `"STAGE1_FAILED"` to `SESSION_STATE_VALUES` in the baseline
   `2026_05_14_0001_initial_schema.py` (for fresh DBs + the lockstep test).
2. New migration `0043` (down_revision `0042`):
   `ALTER TYPE session_state ADD VALUE IF NOT EXISTS 'STAGE1_FAILED'`
   (idempotent; downgrade no-op — Postgres enums have no DROP VALUE).

## Acceptance criteria
- [ ] AC-1: `alembic upgrade head` applies migration 0043 cleanly against Postgres (run in the api container).
- [ ] AC-2: `tests/integration/test_migrations.py::test_baseline_enums_match_python_enums` passes (baseline now contains STAGE1_FAILED).
- [ ] AC-3: full backend unit suite stays green.

## DRY / SOLID check
- **Reuses the established pattern** (0030 + the baseline list) — no new helper,
  no new mechanism. One additive enum value.
- **OCP**: additive enum value; no behavior branching changed.

## Out of scope
- The note-gen `max_tokens` truncation — that's a **runtime AppConfig** value
  (`model_params.note_generation.max_tokens`), raised via the admin Config page /
  AppConfig console to 16000 (the thing that actually un-truncates the note);
  not a code change.
- Gemini JSON robustness / a JSON-repair layer.
- The provider override (Gemini) — operator config, unchanged.
- PR #572 (separate, on hold).

## Test plan (executable)
1. `docker exec aurion-api alembic upgrade head`  → migration 0043 applies, enum has the value.
2. `cd backend && python3 -m pytest tests/integration/test_migrations.py -q`  → green.
3. `cd backend && python3 -m pytest tests/unit -q`  → green.
4. `ruff check` on the new migration.

## Security implications
- Schema-only, additive enum value. No PHI, prompts, secrets, masking, or consent
  paths touched. No data migration; downgrade is a no-op (documented). The new
  value is referenced only by application code on a fresh connection after the
  migration commits (Postgres ADD VALUE in-txn caveat respected, per 0030).
