# Plan for #76 — Alerting & notifications (foundation)

## Task
**#76** — Foundational alert publisher: persisted alert records with
publish/list, and one wired failure trigger (Stage 1 failures). Email/SMS
sinks, the SLA-breach trigger, the acknowledge flow, and the Web Portal UI
land as follow-up issues — this PR proves the architecture.

## Why
CLAUDE.md §"Non-Negotiable Technical Rules" makes auth, masking, and audit
log enforceable but has nothing for *operational* signals. Today, when a
Stage 1 generation fails or a transcription provider errors out, the only
trail is the audit-log entry — a compliance officer wouldn't notice unless
they read every row. #76 introduces an explicit alerts surface so the
portal (and, in follow-ups, email/SMS sinks) can route signals out of band.

## Approach
- **Model + migration**: `Alert` row with `id`, `alert_type`, `severity`,
  `source`, `message`, `metadata` (jsonb), `created_at`, `acknowledged_at`,
  `acknowledged_by`. Migration `0007_alerts`.
- **Service**: `app/modules/alerts/service.py` — `AlertService.publish()`
  (insert + return id), `list()` (paginated/filterable). DI via
  `get_alert_service()`.
- **Trigger wiring**: explicit publish at one trigger site
  (`transcription.py` STAGE1_FAILED path) — 4 lines added. Other failure
  paths (STAGE2_FAILED in notes.py + vision/service.py, TRANSCRIPTION_FAILED,
  masking_failed) move in follow-up PRs so this PR stays scoped. No
  `write_audit` refactor; explicit-site wiring keeps coupling at the
  trigger, not at the audit boundary.
- **Endpoint**: `GET /api/v1/admin/alerts` — ADMIN + COMPLIANCE_OFFICER,
  paginated, filterable by `status` (open/acknowledged) and `severity`.
- **Best-effort publish**: `AlertService.publish` failures are caught at
  the trigger site so an alert-DB hiccup never breaks the audit-log write
  path it sits next to.

## Acceptance criteria
- [ ] **AC-1**: `Alert` model + migration exist; `alembic upgrade head`
      creates the `alerts` table.
- [ ] **AC-2**: `AlertService.publish(...)` returns a UUID and persists a
      row; verified by `pytest tests/unit/test_alert_service.py::test_publish_persists_row`.
- [ ] **AC-3**: `AlertService.list(...)` filters by status + severity;
      verified by `pytest tests/unit/test_alert_service.py::test_list_filters`.
- [ ] **AC-4**: `GET /api/v1/admin/alerts` returns paginated list,
      ADMIN-gated; verified by `pytest tests/integration/test_alerts_api.py`.
- [ ] **AC-5**: STAGE1_FAILED audit write also publishes an alert
      (best-effort; doesn't fail the audit); verified by
      `pytest tests/unit/test_alert_service.py::test_stage1_failure_publishes_alert`.
- [ ] **AC-6**: Backend test suite stays green; verified by
      `cd backend && python3 -m pytest -q`.

## DRY / SOLID check
- **Existing helpers reused**: `Depends(get_db)`, `UserRole`, `require_role`,
  `AsyncSession`, `sqlalchemy.select`, the admin-router aggregator pattern
  from `app/api/v1/admin/__init__.py`, `utcnow`.
- **New helper introduced?** `AlertService` + `get_alert_service()` — yes,
  but new module boundary (alerts), pattern mirrors `users` and `eval`
  modules. Not a third copy; new vertical.
- **SRP**: model = persistence, service = business logic, router = HTTP
  boundary, trigger sites publish.
- **OCP**: new severities extend the enum; new triggers extend the
  trigger-site set without touching `AlertService`.
- **DIP**: db injected via `Depends(get_db)`; service factory pattern.

## Out of scope (deferred follow-ups)
- Email sink (SES) and SMS sink (SNS) + admin-configurable channels.
- Acknowledge / dismiss flow (PATCH endpoint + UI).
- Web Portal UI (Alerts page + sidebar item).
- Additional trigger wires: STAGE2_FAILED, TRANSCRIPTION_FAILED, VISION_FRAME_FAILED, masking_failed.
- SLA-breach trigger (Stage 1 > 30s, Stage 2 > 5min) — needs hook in completion path against `pilot_metrics`.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_alert_service.py -v` → 3 pass
2. `cd backend && python3 -m pytest tests/integration/test_alerts_api.py -v` → all pass
3. `cd backend && python3 -m pytest -q` → 286 → ~290 pass, no regressions
4. `docker-compose exec aurion-api alembic upgrade head` → 0007 applied (smoke)
5. `curl -H "Authorization: Bearer ADMIN:<uuid>" localhost:8080/api/v1/admin/alerts` → 200 + JSON list

## Security implications
- **No PHI in alerts**: `message` and `metadata` fields carry trigger
  identifiers (event_type, session_id) but never patient data. Trigger-site
  publishes are reviewed for PHI before going in.
- **Audit log append-only**: alerts are a separate table, do not interact
  with `audit_log` table semantics. Alert acknowledgement (future) will
  UPDATE the alerts row — explicitly NOT an audit-log mutation.
- **Role-gated**: ADMIN + COMPLIANCE_OFFICER only.
- **Best-effort publish**: trigger-site try/except ensures alert-DB
  unavailability never breaks the audited code path.
