# Custom visit types on onboarding + profile

## Task

#259 — Let clinicians name their own consultation/visit types on iOS onboarding
Step 3, on the iOS Profile edit flow, and on the web portal `/portal/profile`
page. Backend widens validation and emits a no-PHI audit row on every
consultation-types change. Per-type template attachment is out of scope.

## Why

Dr. Marie Gdalevitch flagged on 2026-06-06 that the four hard-coded checkboxes
on Step 3 (New Patient / Follow-up / Pre-Op Assessment / Post-Op Follow-up)
don't fit surgical sub-specialty workflows — she wants "LL new pt" / "LL fu"
for lower-limb, and Dr. Perry Gdalevitch wants "breast visit". The pilot at
CREOQ/CLLC needs the dashboard quick-start tiles (DashboardView.swift)
populated with the labels each physician actually uses, not the generic ones.
Constraint context: CLAUDE.md `Pilot at CREOQ/CLLC with Dr. Perry Gdalevitch
(plastic surgeon) and Dr. Marie Gdalevitch (orthopedic surgeon).` and the
`feedback_premium_ui_design_system` saved memory ("EN+FR strings at parity",
"build iOS UI on Theme.swift tokens/animations").

## Approach

Single vertical slice — backend + iOS + web — in one lane, one PR.

**Files touched:**

- `backend/app/core/text_validation.py` — NEW. Extract the cheap PHI
  format gate that already exists at
  `backend/app/api/v1/sessions.py::_check_identifier_format` into a shared
  `validate_user_text(value, max_length, *, reject_full_name)` helper. This
  is the third copy of the pattern (sessions.py + profile.py + the upcoming
  custom-types path), which meets §6c "third copy → abstract" gate.
- `backend/app/api/v1/sessions.py` — replace `_check_identifier_format` body
  with a thin wrapper around `validate_user_text(..., max_length=64,
  reject_full_name=True)`. Same exception strings, same behaviour, same tests.
- `backend/app/api/v1/profile.py` — add a `_validate_consultation_types`
  field_validator on `UpdateProfileRequest` that uses `validate_user_text`
  for each entry. Diff old vs new in the route handler, emit
  `PROFILE_CONSULTATION_TYPES_UPDATED` with **counts only**.
- `backend/app/core/audit_events.py` — new enum member
  `PROFILE_CONSULTATION_TYPES_UPDATED` + kwarg whitelist
  `{actor_id, count_before, count_after, defaults_added, defaults_removed,
  customs_added, customs_removed}`. Names of custom types NEVER in the payload.
- `backend/tests/integration/test_profile_consultation_types.py` — NEW.
- `backend/tests/unit/test_text_validation.py` — NEW. Pure-function gates.
- `backend/tests/unit/test_audit_events.py` — extend enum-name test for the
  new event.
- `ios/Aurion/Aurion/App/PhysicianProfileSetupView.swift` — extend Step 3
  with a custom-types list + an "Add custom type" inline field. Cheap
  client-side format gates mirror the backend.
- `ios/Aurion/Aurion/App/ProfileView.swift` — show custom-types alongside
  defaults; the existing "Edit Practice" button (already wired) sends the
  user back to `PhysicianProfileSetupView` for edits, so reuse the same
  component there. AC-5 met by making Step 3's custom-types UI the single
  edit surface — no second editor screen.
- `ios/Aurion/Aurion/Resources/{en,fr}.lproj/Localizable.strings` —
  new `setup.visit.custom.*` strings.
- `ios/Aurion/AurionTests/CustomVisitTypeTests.swift` — NEW. Unit tests
  for the format-gate helper + the add/delete state transitions on the
  view model layer.
- `web/app/portal/profile/page.tsx` — replace the `MultiSelect` for
  consultation_types with a new `ConsultationTypesEditor` component:
  default chips + custom chips + "Add custom type" field. Client-side
  validation mirrors backend.
- `web/components/portal/ConsultationTypesEditor.tsx` — NEW. Pure
  presentation component with an exported `validateConsultationType` helper.
- `web/messages/{en,fr}.json` — extend `Profile.consultationTypes.*` with
  `custom.add`, `custom.label`, `custom.placeholder`, `custom.empty`,
  `custom.limitReached`, plus validation messages
  (`validation.tooLong`, `validation.ssn`, `validation.email`,
  `validation.name`, `validation.empty`).
- `web/tests/CustomVisitTypes.spec.tsx` — NEW.

**Subagent assignments:**

- Backend changes — direct edits + `@test-writer` for the integration test.
- iOS changes — direct edits + UI patterns matching existing `checkboxRow`
  / `prefsToggleRow` / `prefsStepperRow` shapes (Theme.swift tokens).
- Web changes — direct edits + a small component with vitest coverage.

## Acceptance criteria

Each criterion is objectively verifiable.

- [ ] **AC-1** iOS onboarding Step 3 keeps the 4 default checkboxes AND shows
  an "Add custom type" affordance below the list. Tapping it reveals an
  inline `TextField` with Add and Cancel actions. Verified by reading
  `PhysicianProfileSetupView.swift::visitTypesStep` and the iOS unit test
  `CustomVisitTypeTests.testAddCustomTypeAddsToList`.
- [ ] **AC-2** Each added custom type renders as a row with a checkmark and
  a trash-icon delete affordance. Deletion removes the type from the
  `consultationTypes` set in-place. Verified by
  `CustomVisitTypeTests.testDeleteCustomTypeRemovesFromList`.
- [ ] **AC-3** Soft limit of 20 custom types — when at the limit, the Add
  affordance is disabled with a hint string. Verified by
  `CustomVisitTypeTests.testLimitReachedDisablesAdd`.
- [ ] **AC-4** Each custom type's name passes:
  `len(stripped) > 0`, `len(stripped) <= 60`, no raw 9-digit SSN, no
  dashed SSN, no `@`, not a multi-token alpha "full name" pattern.
  Backend enforces the same gates in
  `validate_user_text(max_length=60, reject_full_name=True)`. Verified by
  `backend/tests/unit/test_text_validation.py::test_consultation_type_gates`.
- [ ] **AC-5** iOS Profile screen surfaces both default and custom types
  in the Practice Settings card via `localizedConsultationType()`
  (default keys → resolved string; custom values → display verbatim via
  `displayFormatted` fallback). The existing "Edit Practice" button sends
  the user back to `PhysicianProfileSetupView` where the same custom-types
  UI is the edit surface. Verified by reading
  `ProfileView.swift` lines 174-178 + manual flow in the iOS test plan.
- [ ] **AC-6** Web portal `/portal/profile` shows the four default
  consultation types as toggleable chips + a custom-types list with an
  "Add custom type" input + delete buttons on each custom row. Save
  persists both default toggles and custom entries through the existing
  `PUT /profile`. Verified by `web/tests/CustomVisitTypes.spec.tsx`.
- [ ] **AC-7** Backend `PUT /profile` accepts `consultation_types: list[str]`
  with the four defaults legal AND arbitrary user strings legal under the
  format gates above. Verified by
  `backend/tests/integration/test_profile_consultation_types.py::test_acceptsCustomTypes`
  and `::test_rejectsTooLongType`.
- [ ] **AC-8** Backend emits exactly one `PROFILE_CONSULTATION_TYPES_UPDATED`
  audit row per change with payload
  `{actor_id, count_before, count_after, defaults_added, defaults_removed,
  customs_added, customs_removed}` — NEVER the type names. Same-list updates
  emit zero rows. Verified by
  `backend/tests/integration/test_profile_consultation_types.py::test_emitsAuditWithCountDeltasOnly`
  and `::test_noChange_skipsAuditEmit`.
- [ ] **AC-9** All new strings have EN + FR (Québec) parity:
  - iOS — keys exist in both `en.lproj/Localizable.strings` and
    `fr.lproj/Localizable.strings`.
  - Web — `Profile.consultationTypes.custom.*` exists in both `en.json`
    and `fr.json`. Verified by `web/tests/CustomVisitTypes.spec.tsx::test_i18nParity`.
- [ ] **AC-10** All local CI green before push:
  `cd backend && python3 -m ruff check . && python3 -m pyright app/ && python3 -m pytest -q`
  and `cd web && npm run lint && npx tsc --noEmit && npx vitest run`.

## DRY / SOLID check

- **Existing helpers reused**: `write_audit` (`backend/app/api/v1/_helpers.py`),
  `get_or_create_profile` + `update_profile`
  (`backend/app/modules/profile/service.py`), `_PROFILE_AUDIT_SESSION`
  synthetic UUID anchor (already used by `TEAM_MEMBERS_UPDATED`),
  `localizedConsultationType` + `displayFormatted` (`Theme.swift`),
  `MultiSelect` + `Field` sub-components (`web/app/portal/profile/page.tsx`),
  `setProfile` / `updateMyProfile` (`web/lib/portal-api.ts`).
- **New helper introduced?** Yes — `validate_user_text` in
  `backend/app/core/text_validation.py`. This is the **third** copy of the
  format-gate pattern: it already exists at `sessions.py::_check_identifier_format`
  and would have been duplicated in `profile.py::_validate_consultation_types`
  + the iOS-side gates. The third copy triggers the §6c "abstract" rule.
  `_check_identifier_format` is rewritten as a thin wrapper around
  `validate_user_text` to avoid behavioural drift between the patient
  identifier path and the consultation-type path.
- **iOS UI tasks — `mobile-ios-design` consulted**: Yes, applied the
  "Inline-Add" SwiftUI pattern (inline `TextField` with Add/Cancel chip
  actions, swipe-to-delete on list rows) per HIG "Allow people to add
  custom entries inline rather than via modal sheets" — matches the
  existing `prefsStepperRow` / `prefsPickerRow` shape that PR #251 settled on.

## Out of scope

- Per-type template attachment (a clinician can't say "LL new pt → orthopedic
  template" yet). Future enhancement.
- Reordering custom types — the UI shows them in insertion order; we do
  not surface drag handles. Cheap to add later if a clinician asks.
- Backend uniqueness constraint — two clinicians can independently coin
  the same custom type string; that's fine, the data is per-profile.
- Migration of any existing rows — the column already stores arbitrary
  JSON strings, so existing rows are forward-compatible without a migration.

## Test plan (executable)

```bash
# Backend
cd backend && python3 -m ruff check .
cd backend && python3 -m pyright app/
cd backend && python3 -m pytest -q tests/unit/test_text_validation.py tests/integration/test_profile_consultation_types.py tests/unit/test_audit_events.py -v
cd backend && python3 -m pytest -q

# Web
cd web && npm run lint
cd web && npx tsc --noEmit
cd web && npx vitest run tests/CustomVisitTypes.spec.tsx
cd web && npx vitest run

# iOS (sanity — full xcodebuild is gated by CI; locally we run unit tests)
# (Local Xcode build optional; PR's CI runs the iOS workflow.)
```

## Security implications

- Touches PHI surfaces? Indirectly — custom types are user-authored
  free-text. Defence: format-gate (no SSN, no email-shape, no full-name
  shape, ≤60 chars, ≤20 entries). Defence in depth: the audit row carries
  COUNTS ONLY, never the type names; if a clinician slips a name past the
  gate the immutable trail still doesn't carry it.
- Touches audit log? Yes — new `PROFILE_CONSULTATION_TYPES_UPDATED` event,
  append-only via `write_audit`. Kwarg whitelist enforced by
  `audit_events.py::PAYLOAD_FIELDS`.
- Touches AI prompts / consent gate / Secrets? No.
- Touches recording / masking? No.
