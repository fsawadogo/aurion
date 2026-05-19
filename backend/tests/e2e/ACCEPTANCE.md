# P0-07 — Backend E2E Smoke Test (Acceptance Criteria)

## Goal

A single, fast, repeatable pytest test that exercises the full session
lifecycle end-to-end against the real FastAPI router stack and real
Postgres schema, with provider/AWS boundaries mocked. Catches wiring
regressions — bad routes, broken state transitions, missing audit
events, schema drift — that unit tests miss.

## Out of scope

- Real AI provider calls (mocked at the registry boundary).
- Real AWS calls (AppConfig, S3, DynamoDB, Comprehend Medical — all mocked).
- WebSocket streaming (covered by unit tests).
- Async Stage 2 job runner end-to-end (covered by stage2_jobs unit tests).
- iOS / web — backend only.

## Approach

In-process pytest:

- `httpx.AsyncClient` + `ASGITransport` against the FastAPI `app` object.
- Real local Postgres (`postgresql+asyncpg://aurion:aurion@localhost:5432/aurion`)
  with **per-test transactional isolation** — every test runs inside a
  SAVEPOINT and rolls back at teardown. No data persists between tests.
- `app.dependency_overrides[get_db]` injects the per-test session.
- Provider registry, AuditLogService, AppConfigClient, and boto3 clients
  all swapped out with AsyncMock/MagicMock at fixture scope.
- Marker `@pytest.mark.e2e`. Tests `skip` automatically if
  `pg_isready` fails on `localhost:5432`.

## Test surface

### Test 1 — happy-path session lifecycle (no audio)

Walks the state machine without any actual audio upload:

| Step | Endpoint | Expected state |
|---|---|---|
| Create session | `POST /api/v1/sessions` | `CONSENT_PENDING` |
| Start without consent | `POST /api/v1/sessions/{id}/start` | **403/409 — hard block** |
| Confirm consent | `POST /api/v1/sessions/{id}/consent` | `CONSENT_PENDING` (consent flag flips) |
| Start recording | `POST /api/v1/sessions/{id}/start` | `RECORDING` |
| Pause | `POST /api/v1/sessions/{id}/pause` | `PAUSED` |
| Resume | `POST /api/v1/sessions/{id}/resume` | `RECORDING` |
| Stop | `POST /api/v1/sessions/{id}/stop` | `PROCESSING_STAGE1` |
| Pause from processing | `POST /api/v1/sessions/{id}/pause` | **409 — invalid transition** |
| Fetch session | `GET /api/v1/sessions/{id}` | matches created session |

Assert on the audit log mock that the following events were emitted, in
order: `session_created`, `consent_confirmed`, `recording_started`,
`recording_paused`, `recording_resumed`, `recording_stopped`.

### Test 2 — Stage 1 → approve → export → purge

Picks up after `stop`:

| Step | Surface | Expected |
|---|---|---|
| Stage 1 simulated complete | Insert `NoteVersionModel(version=1)` directly via fixture | session moves to `AWAITING_REVIEW` |
| Fetch latest note | `GET /api/v1/notes/{session_id}` | returns version 1 |
| Approve note | `POST /api/v1/notes/{session_id}/approve` | `REVIEW_COMPLETE` |
| Export DOCX | `POST /api/v1/export/{session_id}` body `{"format":"docx"}` | 200 + non-empty bytes |
| Purge confirmation | audit log shows `raw_data_purged` event | mock receives the call |

Note generation provider is mocked to return a canned Stage 1 payload
matching the schema in CLAUDE.md (one populated section with one claim
and a valid source_id).

## Files

- `backend/tests/e2e/conftest.py` — fixtures.
- `backend/tests/e2e/test_session_lifecycle.py` — Test 1 + Test 2.
- `backend/tests/e2e/ACCEPTANCE.md` — this file.
- `backend/pyproject.toml` or `backend/pytest.ini` — register the `e2e`
  marker so `pytest --strict-markers` is happy.

## Run

```bash
# Pre-req: docker compose up -d (just Postgres needed)
cd backend && python3 -m pytest tests/e2e -m e2e -v
```

Auto-skips if Postgres is unreachable on `localhost:5432` — keeps the
test runnable on CI runners that don't have a database, the same suite
that gates feature work.

## DRY / SOLID gates

- **DRY:** the fixture file owns one `app_client` and one `db_session`
  fixture; tests do not re-implement client setup or DB connection
  logic. State transitions are walked via helper functions on the
  fixture file (`walk_to_recording(client, session_id)`), reused if a
  third test joins the file. Will *not* abstract earlier than that.
- **SRP:** conftest fixtures are scoped narrowly — `db_session` only
  handles DB, `mock_providers` only handles provider registry,
  `app_client` only handles HTTP. No god-fixture.
- **DIP:** tests depend on `app_client` (an abstraction over HTTP) and
  fixtures — never on `httpx.AsyncClient` or `AsyncSession` directly.

## Risk + mitigation

- **High-risk:** the transactional rollback pattern with async SQLAlchemy
  + nested savepoints is fiddly. The `expire_on_commit=False` config on
  `async_session_factory` may interact badly with session cleanup.
  Mitigation: smoke-test the fixture in isolation first (one trivial
  test that just creates + reads a SessionModel and verifies rollback)
  before layering on the real test.
- **Medium-risk:** `AppConfigClient.start_polling` boots a background
  task during `lifespan`. The lifespan must be skipped or the task
  cancelled in fixtures.
- **Low-risk:** the dev token format (`<role>:<user_id>`) means we don't
  need to mock Cognito — we just hand-craft a `CLINICIAN:{uuid}` token.
