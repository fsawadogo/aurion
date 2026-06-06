# Plan — #260 iOS · wire Edit Team Members sheet on Profile

## Task

GH-260 — Tapping "Edit Team Members" in `ProfileView` flips a state flag but
no `.sheet` / `.fullScreenCover` observes it. Wire a sheet that lets the
clinician add / remove allied-health team members and persists changes via
`PUT /profile`.

## Why

Dr. Marie Gdalevitch flagged this on 2026-06-06 during pilot validation: she
hits the button, nothing happens, and she has no way to register her usual
team (nurses, scribes, residents) without losing the profile data she
entered during onboarding. The team-members list feeds into the
specialty-template prompt (so the LLM knows who's in the room) and the
session UI (so the right names surface during speaker-tagging) — leaving it
unreachable post-onboarding blocks both for the pilot. CLAUDE.md §"Build
Order — Phase 7 iOS" makes the iOS app the consumer of `PhysicianProfile`
fields edited from Profile; this PR closes the missing surface.

## Approach

Single-file UI patch + one new SwiftUI view. No backend route changes — the
existing `PUT /profile` already accepts `allied_health_team`. Backend gets
one new audit event (`TEAM_MEMBERS_UPDATED`) so compliance has a row for
each save; iOS just calls `updateProfile` and the route handler emits.

### Files to touch

- `ios/Aurion/Aurion/App/ProfileView.swift` — wire `.sheet(isPresented: $showTeamMemberEditor)`.
- `ios/Aurion/Aurion/App/TeamMemberEditorView.swift` (new) — the sheet body:
  list + swipe-to-delete + inline "add member" form. Builds on
  `Theme.swift` tokens (`AurionSpacing`, `aurionFont`, `AurionIconBubble`).
- `ios/Aurion/Aurion/Resources/en.lproj/Localizable.strings` — new
  `profile.teamEditor.*` keys.
- `ios/Aurion/Aurion/Resources/fr.lproj/Localizable.strings` — Québec FR
  parity. Same keys.
- `backend/app/core/audit_events.py` — append `TEAM_MEMBERS_UPDATED` member
  + whitelist entry (`{"actor_id", "members_count_before", "members_count_after"}`).
- `backend/app/api/v1/profile.py` — emit `TEAM_MEMBERS_UPDATED` in
  `update_profile_route` when `allied_health_team` is in the request body
  and the count actually changed. Uses the synthetic auth-audit session id
  (same pattern as `MFA_DISABLED` etc.) because profile updates aren't
  session-scoped.
- `backend/tests/unit/test_audit_events.py` — append the new enum member to
  `EXPECTED_VALUES` so the locked-values test passes.
- `ios/Aurion/AurionTests/TeamMemberEditorViewTests.swift` (new) — view-side
  contracts: AlliedHealthMember CRUD on the buffer, persist-on-dismiss
  closure invoked with the right diff, EN+FR strings parity.

### Subagent assignments

- `@ios-builder` for the SwiftUI view + `ProfileView` wiring.
- `@backend-builder` for the audit event addition.
- `@test-writer` for both the iOS and backend test additions.
- `@compliance-checker` after both edits to confirm no PHI in audit payload.

## Acceptance criteria

- [ ] AC-1: Tapping "Edit Team Members" in `ProfileView` presents the
      `TeamMemberEditorView` sheet immediately, verified by
      `TeamMemberEditorViewTests.profileView_wiresEditTeamSheet` (state
      flip → `body` reads the sheet modifier).
- [ ] AC-2: Sheet shows current team members from
      `appState.physicianProfile.alliedHealthTeam` as rows with name + role
      and `.onDelete` removes a row in place. Test:
      `TeamMemberEditorViewTests.deleteRow_removesFromBuffer`.
- [ ] AC-3: "Add member" row at the bottom expands to an inline form with
      Name (required), Role (required, free text), optional Email; tapping
      "Add" appends to the buffer and resets the form. Test:
      `TeamMemberEditorViewTests.addRow_appendsValidMember_resetsForm`.
- [ ] AC-4: Dismissing the sheet via the top-right "Done" button persists
      the buffer via `APIClient.updateProfile(["allied_health_team": ...])`;
      a system swipe-down dismiss without changes does NOT call the API.
      Test: `TeamMemberEditorViewTests.done_persistsBuffer` and
      `swipeDismiss_withNoChanges_doesNotPersist`.
- [ ] AC-5: After persist, `appState.physicianProfile` is updated with the
      response so the Profile card reflects the new count. Test:
      `TeamMemberEditorViewTests.done_updatesAppStateProfile`.
- [ ] AC-6: Empty buffer state still renders the existing
      `profile.noTeam` empty-state copy (no change to that contract).
      Test: `TeamMemberEditorViewTests.emptyBuffer_rendersEmptyCopy`.
- [ ] AC-7: EN + FR (Québec) strings parity for every new
      `profile.teamEditor.*` key. Test:
      `TeamMemberEditorViewTests.editorStrings_resolveInEnAndFr` walks both
      `Bundle(forLanguage:)` lookups.
- [ ] AC-8: Backend emits `TEAM_MEMBERS_UPDATED` audit event on
      `allied_health_team` change, carrying only
      `{actor_id, members_count_before, members_count_after}`. Test:
      `backend/tests/unit/test_audit_events.py::test_audit_event_type_values_locked`
      passes after the new member is added to `EXPECTED_VALUES`.
- [ ] AC-9: 60-char hard cap per name + role field, enforced client-side on
      the inline form (truncates with `.onChange`). Test:
      `TeamMemberEditorViewTests.nameField_capsAt60Characters`.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - `AlliedHealthMember` (`Network/APIClient.swift:1665`) — value type, used
    as-is. Currently has `name + role`; we extend it with an OPTIONAL
    `email: String?` so the JSON round-trip stays backward-compatible (the
    backend persists `list[dict]` so unknown keys round-trip transparently;
    iOS decoder treats missing email as nil).
  - `APIClient.updateProfile(_:)` (`Network/APIClient.swift:418`) — already
    accepts an arbitrary `[String: Any]` PATCH-style update. No new method
    needed.
  - `AurionSpacing`, `aurionFont`, `AurionIconBubble`, `SectionHeader`,
    `AurionHaptics`, `L(...)` — design-system primitives already used in
    `ProfileView`. The new sheet builds on the same tokens.
  - `write_audit` + `get_audit_log_service` (backend) — existing helpers.
    `_AUTH_AUDIT_SESSION` synthetic id pattern from `me_security.py`
    transplanted here.
- **New helper introduced?**: **No.** `TeamMemberEditorView` is one new
  SwiftUI view (presentational); no shared abstraction is extracted. We
  considered a generic "list-edit sheet" helper but team-members is the
  first instance — extracting on first sight would be premature (§6c rule
  of three).
- **iOS UI tasks only — `mobile-ios-design` consulted**: **yes.** Pattern
  applied: standard iOS "sheet of editable list with `.onDelete` + inline
  form footer" (HIG: "Use sheets for short, focused tasks where dismissal
  saves state"). `.sheet(isPresented:)` over `.fullScreenCover(...)`
  because the task is short and the user benefits from peeking the Profile
  underneath (HIG: "Sheets feel less intrusive when the dismissed context
  remains visible").

## Out of scope

- **Server-side max-2 enforcement:** the existing
  `update_profile` service caps the team at 2 members
  (`if len(team) > 2: raise ValueError`). The pilot clinicians typically
  work with 3-5 people; lifting the cap is its own scope (validate against
  pilot needs, decide on a new cap or none, update tests). Filed as backlog
  entry "AUR-PROFILE-TEAM-CAP-LIFT". The iOS editor still enforces a
  client-side soft warning at 2 members so the save doesn't surprise-fail
  until the backend is updated.
- **Team-member role pre-fill suggestions** (RN, PA, resident, scribe,
  MOA…) — the issue body mentions these as examples; we ship a free-text
  field for the pilot. A picker can land later via
  `AUR-PROFILE-TEAM-ROLE-PICKER`.
- **Email validation / verification** — we store the optional email
  verbatim if provided. No format check, no verification flow.
- **Audit of WHICH members changed** (added vs removed names) — we record
  only the count delta. Names are workforce data and stay out of the
  immutable audit log by design (CLAUDE.md "No PHI in logs/errors/responses"
  + the audit-event docstring rule: "personal phrasing stays out of the
  immutable trail" — applied here to staff names too).

## Test plan (executable)

1. **Backend audit-event lock holds:**
   `cd backend && python3 -m pytest tests/unit/test_audit_events.py -v` →
   the locked-values test passes after the new member is added.
2. **Backend route emits the audit event on team-list change:** add a
   `tests/integration/test_profile_team_audit.py` exercising
   `PUT /profile` with `{"allied_health_team": [...]}` and asserting one
   `team_members_updated` row landed via the mock audit service.
3. **iOS unit tests pass:**
   `cd ios/Aurion && xcodebuild test -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing AurionTests/TeamMemberEditorViewTests`.
4. **iOS build green on both targets** — universal-app rule (§verify):
   - `xcodebuild -project Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build` → BUILD SUCCEEDED
   - `xcodebuild -project Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M4)' build` → BUILD SUCCEEDED
5. **Manual smoke** (post-merge, pilot device):
   - Open Profile → tap "Edit Team Members" → sheet appears.
   - Add 2 members, swipe-delete one, tap Done.
   - Reopen Profile → card shows the surviving member.
   - Reopen sheet → buffer matches what was saved.

## Security implications

- **PHI / audit log:** new `TEAM_MEMBERS_UPDATED` event carries only the
  actor UUID and count-delta integers. NO names, NO emails. Matches the
  pattern set by `MACRO_CREATED` (which excludes the macro body) and
  `PROMPT_USER_PROMPT_SET` (which excludes the prompt text).
- **Append-only audit log:** unchanged — we add an emit site, not a
  mutation. The `write_audit` helper itself enforces append-only.
- **Descriptive mode:** no new AI prompt. Not applicable.
- **Consent gate:** Profile is reachable only when authenticated; the
  Profile route is already behind `get_current_user`. No change.
- **Secrets / provider registry:** untouched.
- **Provider traceability:** untouched (no AI call).
- **iOS Keychain only for voice embedding:** untouched (no biometric
  surface in this PR).
- **Per-view contract:** the iOS editor never persists the email field
  anywhere except into the JSON column the backend already accepts —
  keeping iOS as a transparent client of the existing schema means no new
  PHI handling needs to be reviewed.
