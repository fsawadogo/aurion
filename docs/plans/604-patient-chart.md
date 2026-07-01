# Plan — #604 Patient Chart Workspace (cross-clinician, elevated-role, flag-dark)

## Task
Build the cross-clinician **Patient Chart** — an aggregated "every encounter for
this patient, across all staff" view — for the pilot. Two product decisions
(2026-07-01) fix the shape:

- **Visibility = elevated-role only.** Only `CLINICAL_ADMIN` / `ADMIN` see the
  cross-staff chart. Regular `CLINICIAN`s keep their existing owner-scoped
  `/me/patients/{id}/sessions` view, unchanged. No clinician-to-clinician PHI
  crossing.
- **In-chart action = supervisory validate.** A `CLINICAL_ADMIN` / `ADMIN` can
  approve ("validate") ANY note in the chart. Reuses `approve_note`, which since
  #606 refuses to sign off over unresolved Stage-2 conflicts.

Ships **dark behind a new feature flag `cross_clinician_chart_enabled`
(default OFF)** until compliance sign-off — same posture as
`video_import_enabled` / `grounded_synthesis_enabled`. Merging exposes no
cross-clinician PHI until compliance flips the flag.

## Why
MVP scope audit (#604) called out that a patient seen by more than one pilot
clinician has no single longitudinal chart. Cross-clinician matching is feasible
because the patient-identifier HMAC hash is **global/deterministic** (same MRN →
same hash across clinicians), and the lookup is already indexed
(`ix_sessions_external_reference_id_hash`).

## Approach

### Backend
1. **`backend/app/api/v1/admin/patient_chart.py`** (new module, mirrors
   `admin/sessions.py`): `APIRouter(prefix="/admin")`.
   - `GET /admin/patients/{identifier}/encounters` —
     `require_role(CLINICAL_ADMIN, ADMIN)` + flag gate (404 when
     `cross_clinician_chart_enabled` is False, so the surface is truly dark).
     Query = `hash_identifier(identifier)` equality with **no** `clinician_id`
     filter (the cross-clinician fork of `list_my_sessions_by_patient_identifier`).
     Batch-resolve clinician names (`resolve_clinician_names`) + latest note
     version/approval (`note_repo.get_latest_versions_by_session`) to avoid N+1.
     Response rows carry `session_id, clinician_id, clinician_name, specialty,
     state, created_at, note_version, note_stage, is_approved`.
   - `POST /admin/patients/notes/{session_id}/validate` —
     `require_role(CLINICAL_ADMIN, ADMIN)` + flag gate. `get_session_or_404`
     (NOT owner-scoped), replicate the state guard from the clinician approve
     route, `approve_note(session_id, db)` mapping `UnresolvedConflictError` →
     409, `transition_session` → REVIEW_COMPLETE, then emit the new audit event.
2. **`backend/app/api/v1/admin/__init__.py`** — register `patient_chart.router`.
3. **Audit event** (`backend/app/core/audit_events.py`): `NOTE_VALIDATED =
   "note_validated"` in the Notes/review section + `ALLOWED_AUDIT_KWARGS`
   `frozenset({"actor_id", "target_clinician_id", "version"})` — PHI-free
   (UUIDs + int; `session_id` is the partition key, not a kwarg).
   `tests/unit/test_audit_events.py`: add to `EXPECTED_VALUES`.
4. **Feature flag** end-to-end (mirror `grounded_synthesis_enabled`):
   - `infrastructure/appconfig.tf` feature_flags.properties (NOT required).
   - `backend/app/modules/config/schema.py` `FeatureFlagsConfig`
     `cross_clinician_chart_enabled: bool = False`.
   - `backend/app/api/v1/admin/feature_flags.py` `FeatureFlagsResponse`
     (defaulted) + `_build_response` (writer round-trip + mirror test).
   - `backend/app/api/v1/me.py` `PortalFeatureFlagsResponse` +
     `get_portal_feature_flags` (portal read surface).

### Web
5. **`web/lib/portal-api.ts`** — `listAdminPatientEncounters(identifier)` +
   `validateNote(sessionId)`; extend `getPortalFeatureFlags()` return type.
   `web/types/index.ts` — `AdminPatientEncounter`.
6. **`web/app/portal/admin/patients/[identifier]/page.tsx` + `…Client.tsx`** —
   fork the owner page shell; per-note Validate button (disabled when approved /
   surfaces 409 inline); role + flag gate with a "not enabled" empty state.
7. **`web/components/Sidebar.tsx`** — nav entry `roles: ["CLINICAL_ADMIN",
   "ADMIN"]`, hidden while flag is null/false (mirror the video-import gate).
8. **`web/messages/en.json` + `fr.json`** — new `AdminPatientChart` namespace,
   both locales at parity.

## Acceptance criteria
- [ ] AC-1: `GET /admin/patients/{id}/encounters` returns every clinician's
  sessions for the identifier (not just the caller's), with clinician
  attribution + per-note approval status — CLINICAL_ADMIN + ADMIN only.
- [ ] AC-2: A CLINICIAN / EVAL_TEAM / COMPLIANCE_OFFICER calling the endpoint
  gets 403 (role gate).
- [ ] AC-3: With `cross_clinician_chart_enabled = False`, both endpoints 404
  regardless of role (feature dark).
- [ ] AC-4: `POST …/notes/{session_id}/validate` approves ANOTHER clinician's
  note (supervisory) and writes `NOTE_VALIDATED` with actor + target clinician.
- [ ] AC-5: Validate over an unresolved Stage-2 conflict → 409, no approval
  (the #606 invariant holds for the supervisory path).
- [ ] AC-6: New flag round-trips through the admin feature-flags writer without
  resetting other flags (`test_response_mirrors_config_field_for_field`).
- [ ] AC-7: `NOTE_VALIDATED` is in `EXPECTED_VALUES` + has a whitelist entry
  (audit-event guards pass).

## DRY / SOLID
- Reuse `resolve_clinician_names`, `note_repo.get_latest_versions_by_session`,
  `hash_identifier`, `approve_note`, `transition_session`, `get_session_or_404`,
  `write_audit` — no new cross-cutting helpers. New admin routes live in their
  own module (SRP), gated by an explicit `require_role` + flag, never by
  widening `_OWNER_BYPASS_ROLES` (which would silently broaden every existing
  `/sessions`/`/notes` route).

## Security implications
- Cross-clinician PHI is exposed ONLY behind (role gate ∧ flag), both required.
  Default OFF ships the feature dark. Identifier stays hashed for lookup; the
  plaintext identifier is never logged and the audit event carries only UUIDs +
  a version int (no identifier, no clinical content). Supervisory approval
  inherits the #606 conflict gate.

## Out of scope
No change to the owner-scoped clinician chart, note versioning, conflict
resolution flow, or existing admin session/eval surfaces. No NURSE role (#615).
No cross-clinician *edit* — validate (approve) only; authors still edit their own.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_patient_chart_admin.py tests/unit/test_audit_events.py -q`
2. Flag mirror: `python3 -m pytest tests/unit/test_feature_flags*.py -q`
3. `ruff check` the changed files; `python3 -c "import app.api.v1.admin"` clean.
4. Web typecheck/build in CI (web.yml).
