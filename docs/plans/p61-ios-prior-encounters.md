# Plan — #61 prior-encounters rail + full list on NoteReviewView

## Task

#61 iOS: longitudinal cross-encounter context UI — surface prior sessions for
the same patient identifier on `NoteReviewView`, with a tappable rail (≤ 5
preview cards) and a full-screen list (all encounters, newest first).

This is the consumer side of PR #164 (backend `external_reference_id` column
+ `GET /me/patients/{identifier}/sessions` endpoint + iOS identifier
set/clear UI + portal search). The clinician can now SEE the prior context
inline while reviewing today's note, not just on the inbox row.

## Why

CLAUDE.md "Specialty Templates" + the longitudinal context journey in
`memory/journey_phase_mapping.md` rely on the clinician seeing prior
encounters with the same patient at the point they're signing today's
note — that's when reuse and continuity decisions get made. Backend
shipped the data in #164; iOS is now what users see.

Backlog: task #108 (`#61 longitudinal patient context — full slice`).

## Approach

Three new files + two edits + i18n.

### New
1. `ios/Aurion/Aurion/Network/APIClient.swift` — extend with one method:
   `listMySessionsByPatientIdentifier(_ identifier: String) async throws -> [PatientSessionMatch]`
   and a sibling `PatientSessionMatch` Codable model mirroring
   `web/types/index.ts:93`. **One** API call site for prior-encounters
   lookup (DRY gate).

2. `ios/Aurion/Aurion/NoteReview/PriorEncountersRail.swift` — horizontal
   rail. Header + ≤ 5 cards + "See all (N)" link when total > 5. States:
   * **loading**: three skeleton cards
   * **populated**: card per encounter, tap → AppNavigation router
   * **empty**: "First encounter with this patient" copy
   * **failure**: `loadFailed @State` + retry block, copying the exact
     pattern shipped in `PatientSummaryCard.retryState` (PR #186)
   Excludes the current session id; excludes `PURGED` (per existing rule
   on the dashboard recent strip).

3. `ios/Aurion/Aurion/NoteReview/PriorEncountersListView.swift` — full
   modal. NavigationStack-wrapped list, pull-to-refresh, retry block on
   failure, identifier chip on each row. Calls the SAME APIClient method.

4. `ios/Aurion/AurionTests/PriorEncountersTests.swift` — unit tests
   per AC list below.

### Edited
5. `ios/Aurion/Aurion/NoteReview/NoteReviewView.swift` — render the rail
   above the prose body when `externalReferenceId` is non-nil. Sheet
   destination for the full list. The rail is wrapped in
   `if let identifier = ...` so empty-identifier sessions get the
   pre-#164 layout unchanged.

6. `ios/Aurion/Aurion/Resources/{en,fr}.lproj/Localizable.strings` — new
   keys (see i18n section below).

### Navigation
Tap a card → `AppNavigation.shared.requestNote(sessionID:)` +
`AppNavigation.shared.requestTab(.sessions)`. SessionsInboxView already
listens on `pendingNoteSessionID` and pushes the matching session onto
its NavigationStack (existing wiring, no new layer).

## Acceptance criteria

- [ ] AC-1: When a session has `externalReferenceId != nil`, the rail
  appears on `NoteReviewView` above the note prose body. When it's nil,
  the rail is absent.
  Verified by: `PriorEncountersRailTests.rail_omitsWhenIdentifierNil()`.

- [ ] AC-2: Rail shows N ≤ 5 most recent prior encounters, sorted
  newest-first, excluding the current session id and any `PURGED`
  session. Verified by: `PriorEncountersRailTests.rail_filtersCurrentAndPurged()`.

- [ ] AC-3: "See all (N)" link renders only when total prior count > 5.
  Verified by: `PriorEncountersRailTests.seeAll_hiddenWhenAtOrBelowFive()`.

- [ ] AC-4: API returns `[]` → rail shows the empty-state copy
  "First encounter with this patient" (EN + FR localized).
  Verified by: `PriorEncountersRailTests.emptyState_rendersFirstEncounterCopy()`.

- [ ] AC-5: API throws → rail shows a Retry block (mirrors PatientSummaryCard).
  Verified by: `PriorEncountersRailTests.failure_surfacesRetry()`.

- [ ] AC-6: Tapping a card calls
  `AppNavigation.shared.requestNote(sessionID:)`. Verified by:
  `PriorEncountersRailTests.tap_emitsNavigationRequest()`.

- [ ] AC-7: PriorEncountersListView renders the complete sorted list
  (no 5-cap), and reuses the SAME API method as the rail (DRY gate).
  Verified by: `PriorEncountersListTests.list_fetchesViaSameAPIMethod()`.

- [ ] AC-8: PHI privacy — the identifier never appears in `print`,
  `os_log`, `Logger`, or `AuditLogger.log(extra:)` calls inside the
  new files. Verified by: `PriorEncountersPHITests.newFiles_haveNoIdentifierLogs()`
  (grep over `PriorEncountersRail.swift`, `PriorEncountersListView.swift`
  for logging primitives + identifier vars).

- [ ] AC-9: EN + FR string parity — every new key has both translations
  populated. Verified by:
  `PriorEncountersI18nTests.allKeys_haveEnAndFrTranslations()`.

## DRY / SOLID check

- **Existing helpers to reuse**:
  * `APIClient.shared` + the generic `get(path:)` for the new endpoint
  * `formatRelativeTime(_:)` for card timestamps (Theme.swift:933)
  * `localizedSpecialty(_:)` for specialty rendering (Theme.swift:873)
  * `sessionStateKind(_:)` + `sessionStateLabel(_:)` + `AurionStatusPill`
    for state badge (AurionUI.swift:209/896/910)
  * `InboxIdentifierChip` for the identifier chip on the list rows
  * `AppNavigation.shared.requestNote(sessionID:)` /
    `requestTab(.sessions)` for navigation (no new router)
  * `L()` / `Lplural()` for strings (Localization.swift)
  * `Theme.swift` tokens for all colors / radii / spacings
  * `AurionHaptics.selection()` on tap
  * `retryState` pattern from `PatientSummaryCard.swift` for the failure
    UI (copied as a sibling helper, not a new shared component — the
    third occurrence will extract per §6c, this is the second)

- **New helper introduced?**: ONE new APIClient method
  (`listMySessionsByPatientIdentifier`) + ONE new Codable struct
  (`PatientSessionMatch`). Both are first-occurrence; no duplication.
  The rail's card row + the list's row are SEPARATE views by design
  (different layouts, different sizes) — extracted prose helpers cover
  the shared bits (timestamp formatting, specialty label, state badge,
  identifier chip already exists).

- **iOS UI tasks — mobile-ios-design consulted**: yes. The rail
  follows the "horizontal scrolling sub-collection above the primary
  content" pattern Apple uses in Photos / Calendar (compact preview
  with "See all"). Each card is a `Button` styled per Theme tokens —
  no plain SwiftUI, no system buttons.

## Out of scope

- Backend changes — the endpoint shipped in #164, no schema bumps.
- Deterministic-hash column for indexed identifier lookup (still a
  linear decrypt scan — pilot scale tolerates it; performance work
  deferred per the existing TODO in `me.py`).
- Rendering prior encounter NOTES inline (we navigate to them via the
  existing inbox stack — opening a separate read-only NoteReviewView
  would duplicate state). The card is the entry point; reading the
  note happens on the existing surface.
- Patient timeline chart / aggregated diagnoses across encounters
  (descriptive-mode boundary — that's interpretive and out per CLAUDE.md).
- Server-side pagination for the full list (caps at the calling
  clinician's total tagged sessions; pilot physicians won't exceed a
  few hundred over the pilot window).

## Test plan (executable)

1. `cd ios/Aurion && xcodebuild -project Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build 2>&1 | tail -20`
   → `BUILD SUCCEEDED`
2. `cd ios/Aurion && xcodebuild -project Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M5)' build 2>&1 | tail -20`
   → `BUILD SUCCEEDED` (M5 substitute documented in PR — M4 not available on this dev box)
3. `cd ios/Aurion && xcodebuild test -only-testing:AurionTests/PriorEncountersTests -project Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' 2>&1 | tail -30`
   → all PriorEncountersTests pass
4. Full AurionTests suite — `xcodebuild test -scheme Aurion ...` → no regression
5. PHI grep — `grep -nE '(print|os_log|Logger|log\\(.*extra)' ios/Aurion/Aurion/NoteReview/PriorEncountersRail.swift ios/Aurion/Aurion/NoteReview/PriorEncountersListView.swift` → no hits that interpolate identifier

## Security implications

- **PHI**: `external_reference_id` is PHI. The new code carries it as a
  `String` only for the API call argument; it's never logged, never
  printed in errors, and never put in `AuditLogger.log(extra:)`. The
  `PriorEncountersPHITests` test enforces this with a regex grep over
  the two new files.
- **Audit log**: this slice is read-only. No new audit events; no new
  write paths.
- **Descriptive mode**: the rail's copy is descriptive ("Prior
  encounters", "First encounter with this patient") — no diagnostic
  or interpretive language.
- **Consent gate**: not touched.

## i18n keys (EN + FR parity)

```
priorEncounters.title              "Prior encounters" / "Visites précédentes"
priorEncounters.titleWith          "Prior encounters · %@" / "Visites précédentes · %@"
priorEncounters.seeAll             "See all (%d)" / "Voir tout (%d)"
priorEncounters.empty              "First encounter with this patient" /
                                   "Première visite avec ce patient"
priorEncounters.loadFailed         "Couldn't load prior encounters." /
                                   "Impossible de charger les visites précédentes."
priorEncounters.retry              "Retry" / "Réessayer"
priorEncounters.fullList.title     "Encounters for %@" / "Visites pour %@"
priorEncounters.fullList.empty     "No prior encounters yet." /
                                   "Aucune visite précédente pour l'instant."
priorEncounters.a11y.tapCard       "Open encounter from %@" /
                                   "Ouvrir la visite du %@"
```

Co-Authored-By: Claude Opus 4.7 (1M context)
