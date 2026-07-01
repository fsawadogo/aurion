# Plan — #603 Clinician Schedule

## Task
603 — Clinician can add patients to a personal schedule, view it, update entry status, and remove entries.

## Why
Closes the last genuinely-missing MVP scope item (Aurion_MVP_Scope_Definition.pdf, Web Portal → **Schedule**: _"User be able to add patients to their schedule."_). It was the only feature in the scope with zero code. Per-clinician, operational (non-clinical) surface; ships behind normal auth, no pilot-flag gating.

## Approach
Vertical slice mirroring the existing per-clinician `/me/*` features (macros is the closest analog). No iOS. Flat backend module + one new table + Alembic migration + `/me/schedule` routes + a web portal page.

CREATE
- `backend/app/modules/schedule/__init__.py`
- `backend/app/modules/schedule/service.py` — owner-scoped CRUD + status-transition validation over `ScheduleEntryModel`; encrypts patient identifier on write, decrypts on read; raises `ScheduleError`.
- `backend/alembic/versions/2026_07_01_0047_schedule_entries.py` — `create_table("schedule_entries")`, revision `"0047"`, `down_revision="0046"`.
- `backend/tests/unit/test_schedule_service.py`
- `web/app/portal/schedule/page.tsx`

MODIFY
- `backend/app/core/models.py` — add `ScheduleEntryModel` (mirror `PhysicianMacroModel`; encrypted + hash identifier columns like `SessionModel`).
- `backend/app/core/audit_events.py` — append `SCHEDULE_ENTRY_ADDED / _STATUS_CHANGED / _REMOVED` enum members + PHI-free `ALLOWED_AUDIT_KWARGS` entries.
- `backend/app/api/v1/me.py` — `ScheduleEntryResponse`, request models, `_to_schedule_response(row)`, five route handlers.
- `web/lib/portal-api.ts` — `listMySchedule / addMyScheduleEntry / updateMyScheduleEntry / removeMyScheduleEntry`.
- `web/types/index.ts` — `ScheduleEntry`, `ScheduleEntryCreate`, `ScheduleEntryStatusUpdate`.
- `web/components/Sidebar.tsx` — nav item `{ href: "/portal/schedule", roles: ["CLINICIAN"] }`.
- `web/messages/en.json` + `web/messages/fr.json` — `Sidebar.nav.schedule` + `Schedule.*` namespace.

## Data model — `schedule_entries`
| column | type | notes |
|---|---|---|
| `id` | UUID PK (`uuid4`) | audit partition key |
| `clinician_id` | UUID, not null, indexed | owner scope; every query filters on it |
| `patient_identifier_encrypted` | LargeBinary, not null | KMS `encrypt_str`; never plaintext |
| `patient_identifier_hash` | LargeBinary, not null, indexed | `hash_identifier()` for dedupe/lookup |
| `status` | Enum(`scheduled,in_progress,completed,cancelled`), default `scheduled` | transition-validated |
| `scheduled_for` | DateTime(tz), nullable | optional slot; no calendar logic |
| `note` | Text, nullable | short free-text, length-capped; never audited |
| `created_at`/`updated_at` | DateTime(tz) | `utcnow` / `server_default now()` |

Unique `(clinician_id, patient_identifier_hash)` for active entries → `IntegrityError` mapped to 409.

## API surface (`/api/v1/me`, CLINICIAN-only)
- `GET /me/schedule?status=` → `list[ScheduleEntryResponse]`
- `POST /me/schedule` `{patient_identifier, scheduled_for?, note?}` → 201
- `PATCH /me/schedule/{entry_id}` `{status?, scheduled_for?, note?}` → 200
- `DELETE /me/schedule/{entry_id}` → 204 (hard delete; audit preserves trail)

Request models use `ConfigDict(hide_input_in_errors=True)` and run `_check_identifier_format` on `patient_identifier` (rejects name/email/SSN 422 without echoing).

## Acceptance criteria
- [ ] AC-1: List is owner-scoped — `test_schedule_service.py::test_list_scoped_to_owner`.
- [ ] AC-2: Add encrypts at rest, returns decrypted — `test_add_encrypts_identifier_roundtrips`.
- [ ] AC-3: Illegal status transition rejected — `test_status_transition_rejects_illegal`.
- [ ] AC-4: Remove of non-owned entry → None/404 — `test_remove_foreign_entry_returns_none`.
- [ ] AC-5: Full-name/email identifier refused before DB write — `test_add_rejects_full_name_identifier`.
- [ ] AC-6: Audit kwargs PHI-free & whitelisted — `test_schedule_audit_kwargs_whitelisted`.
- [ ] AC-7: Non-CLINICIAN gets 403 (`get_current_clinician`).
- [ ] AC-8: Nav item renders only for CLINICIAN.

## DRY / SOLID check
- **Reuse (no re-implementation):** `get_current_clinician` (me.py), `write_audit`/`get_audit_log_service().write_event` (`_helpers.py`), `hash_identifier` (`core.identifier_hash`), `encrypt_str`/`decrypt_str` (`core.kms_encryption`), `_check_identifier_format`→`validate_user_text` (sessions.py/`core.text_validation`), `utcnow` (`core.clock`), `to_uuid` (`core.uuids`), `Base`+`Mapped/mapped_column` idiom, `IntegrityError`→domain-error map from `macros.create_for_owner`; web `fetchWithAuth`, `humanizeError`, `PageHeader/Card/Button/LoadingSkeleton/Badge`, macros page structure.
- **New helper introduced?** No new cross-cutting helper — `schedule/service.py` is a new owner-scoped service mirroring `macros/service.py` (first copy for this domain).
- **iOS UI tasks only:** n/a.

## Out of scope
Calendar/timeline UI, reminders/notifications, EMR/FHIR sync, multi-staff/shared/team schedules, recurring appointments, drag-drop rescheduling, availability/booking logic, conflict detection, iOS. `scheduled_for` is a single optional timestamp with no calendar rendering.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_schedule_service.py -v`
2. `cd backend && python3 -m pytest tests/unit/test_audit_events.py -q` (audit whitelist invariant still holds)
3. `cd backend && python3 -c "import app.main"` (app imports; router wired)
4. `cd web && npx tsc --noEmit` (types compile) and `npm run build` if feasible
5. Migration sanity: `cd backend && python3 -m alembic upgrade head` against dev DB (or offline `alembic upgrade --sql`)

## Security implications
- **PHI:** patient identifier stored KMS-encrypted + HMAC-hashed only (never plaintext), format-gated on write, decrypted solely in owner's response; `hide_input_in_errors=True` keeps rejected values out of 422s/Sentry. `note` PHI-adjacent → never audited.
- **Scoping:** `clinician_id == user.user_id` on every query + CLINICIAN-only route dependency + 404-on-non-owner (non-existence-leaking).
- **Audit:** `SCHEDULE_ENTRY_ADDED/_STATUS_CHANGED/_REMOVED` with PHI-free kwargs only (`actor_id`, `entry_id`, `status`). Append-only, consistent with `MACRO_*`/`ORDER_*` posture.
