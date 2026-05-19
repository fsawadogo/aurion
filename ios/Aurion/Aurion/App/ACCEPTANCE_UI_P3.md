# UI-P3 — List + screen UX improvements (Acceptance)

## Shipped

- **UI-P3a — SessionsInboxView searchable.** `.searchable(text:)` with
  navigation-bar-drawer placement. Filter pipeline composes status
  filter + text search; status-chip counts stay accurate when the
  user has typed a query because text filter runs last. Search
  matches specialty display name and state.
- **UI-P3b — DashboardView iPad readable-measure clamp.** ScrollView
  content caps at 720pt on iPad regular size class, centred. HIG
  readable-measure guidance — wider forces the eye to travel too far
  on long flat dashboard rows. iPhone unaffected.
- **UI-P3c — NoteReviewView conflicts banner.** Sticky amber banner
  at the top of the review surface showing "N conflicts to resolve"
  with a "Show" button that scrolls to the first conflicting
  section via ScrollViewReader. Approve gating is unchanged; only
  surfaces the count and gives a one-tap path to the work.

## Deferred to separate backlog items

The three flow-rewriting design proposals (morphing record button,
NoteReadyView → toast, PostEncounterView → confirmationDialog) require
rework of `SessionManager`'s state machine and the capture flow's
interaction model. These are not "polish" — they're behavior
changes that deserve explicit user review on their own merits.

- **AUR-UX-RECORD-BUTTON** — morphing single record button + waveform
  background on CaptureView. Estimated 1d. Risk: medium-high; current
  multi-button bar is working and gloved-thumb-friendly.
- **AUR-UX-NOTE-READY-TOAST** — convert NoteReadyView from full-screen
  to dashboard toast banner. Estimated 1d. Risk: medium; ripples
  through ContentView routing + SessionManager state transitions.
- **AUR-UX-POST-ENCOUNTER-DIALOG** — convert PostEncounterView from
  full screen to `.confirmationDialog`. Estimated 0.5d. Risk: low;
  smallest of the three but still session-flow behavior change.

These three will be revisited after pilot feedback (Q3 2026).

## Acceptance

```bash
xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build
xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M4)' build
```

Smoke flow:
- Inbox: type a specialty name into the search field → list filters.
  Clear search → list returns. Filter chips still show original counts.
- Dashboard on iPad in landscape: content sits in a centred 720pt
  column; doesn't stretch to full screen edge.
- NoteReviewView with a Stage-2 note containing CONFLICTS claims:
  amber banner appears at the top, tap "Show" → scrolls to the
  first conflicting section.
