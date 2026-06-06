# Plan — bug-274

## Task
#274 — Team editor "Add" does nothing: entering name+role and tapping **Add** closes the form without adding the member.

## Why
In `TeamMemberEditorView.addMemberForm`, the inline form's "Cancel" and "Add" buttons share one `List` row with the default (`.automatic`) button style. In a SwiftUI `List`, a row containing default-styled buttons makes the **whole row** the tap target and fires *every* button's action in declaration order. Tapping anywhere runs "Cancel" first (`resetForm()` clears name/role + hides the form), then "Add" (`addMember()`), whose `guard canAdd` is now false because the drafts were just cleared → no append. Net effect: Add behaves exactly like Cancel. The "Add team member" row button just above already carries `.buttonStyle(.plain)` — the mitigation the form buttons are missing. This blocks team configuration entirely, which speaker attribution depends on.

## Approach
Give each form button its own hit target with `.buttonStyle(.borderless)` (preserves the gold/secondary `.foregroundColor` styling; `.plain` would also work but flattens tint). Two-line change in `ios/Aurion/Aurion/App/TeamMemberEditorView.swift`.

## Acceptance criteria
- [ ] AC-1: both buttons in the form's trailing `HStack` carry an explicit non-`.automatic` button style (`.borderless`) — verified by diff inspection + the build compiling.
- [ ] AC-2: app builds on iPhone 17 and iPad Pro 11" (M4) — CI matrix.
- [ ] AC-3: existing `TeamMemberEditorViewTests` (encode/contentEqual/strings) still pass — no regression to the persistence contract.
- [ ] AC-4 (manual, documented): typing name+role and tapping Add appends the member to CURRENT MEMBERS and Done persists it — verified on a TestFlight/dev build; SwiftUI `List` hit-testing is not unit-testable without a UI-test host.

## DRY / SOLID check
- **Existing helpers to reuse**: mirrors the existing `.buttonStyle(.plain)` on the "Add team member" row in the same file — applying the same idiom, no new helper.
- **New helper introduced?**: No.
- **iOS UI tasks only — mobile-ios-design**: consulted. HIG/SwiftUI pattern: multiple tappable controls inside a `List` row must each declare a button style (`.borderless`/`.plain`) so the row's automatic full-width tap target doesn't swallow and multi-fire them. Standard SwiftUI list-cell control pattern.

## Out of scope
- The participant-model redesign (#275) and the nav-title Dynamic Type truncation (folds into the #271 sweep) — noted on #274, not fixed here.
- Adding a UITest target (none exists today) — see AC-4.

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -destination 'iPhone 17' -only-testing:AurionTests/TeamMemberEditorViewTests` → existing suite green.
2. Diff inspection: both form buttons show `.buttonStyle(.borderless)`.

## Security implications
None. No PHI (name/role are workforce fields, not patient data, already 60-char capped), no audit/secret/AI/consent path. Pure UI hit-testing fix.
