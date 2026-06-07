# Plan — bug-276

## Task
#276 — Sessions inbox shows a gold "Resume" pill on sessions that can't resume recording (AWAITING_REVIEW, PROCESSING_STAGE1/2), and every row opens `SessionNoteView` regardless. Tapping "Resume" should return the user to the recording screen for genuinely resumable sessions.

## Why
`SessionsInboxView.isPending` = `[AWAITING_REVIEW, PROCESSING_STAGE1, PROCESSING_STAGE2]` drives the "Resume" pill, and the row is always a `NavigationLink → SessionNoteView`. So: (a) the affordance is shown where it can't work (recording already stopped) and absent where it should (`PAUSED`/`RECORDING` aren't even in the set), and (b) it never routes to capture. The dashboard already solved this — `resumableSection` (state `RECORDING`/`PAUSED`) routes via `sessionManager.adoptSession`, and a line-327 comment records that the dashboard's pending section was previously mislabeled "Resume" too and fixed in the 2026-06-05 bug bash. The inbox is the remaining copy.

## Approach
Reuse the dashboard's proven mechanism (DRY):
- Add a pure `static rowAction(for state:) -> InboxRowAction` (`.resume` for RECORDING/PAUSED, `.review` for AWAITING_REVIEW, `.status` otherwise).
- Pill: `.resume` → gold "Resume"; `.review` → gold "Review" (string `sessions.review` already exists); `.status` → existing `AurionStatusPill` (PROCESSING now reads as a non-actionable status, not "Resume").
- Row nav: `.resume` → `Button { sessionManager.adoptSession(session) }` (→ CaptureView, identical to the dashboard); `.review`/`.status` → existing `NavigationLink → SessionNoteView`.
- Add `@EnvironmentObject var sessionManager` (already in the tab environment; dashboard uses it).

Files: `ios/Aurion/Aurion/Session/SessionsInboxView.swift`, new `AurionTests/SessionsInboxActionTests.swift`.

## Acceptance criteria
- [ ] AC-1: `rowAction(for: "PAUSED") == .resume` and `"RECORDING" == .resume` — `SessionsInboxActionTests`.
- [ ] AC-2: `rowAction(for: "AWAITING_REVIEW") == .review` (was the mislabeled "Resume") — test.
- [ ] AC-3: `rowAction(for: "PROCESSING_STAGE1") == .status` and `"PROCESSING_STAGE2" == .status` (no "Resume") — test.
- [ ] AC-4: `rowAction(for: "REVIEW_COMPLETE"/"EXPORTED"/"PURGED") == .status` — test.
- [ ] AC-5: app builds iPhone 17 + iPad Pro 11" (M4) — CI.

## DRY / SOLID check
- **Existing helpers to reuse**: `sessionManager.adoptSession(_:)` (the dashboard's resume path — single source of truth for re-engaging capture), existing `sessions.resume`/`sessions.review` strings, `AurionStatusPill`, `AurionHaptics`. No new resume logic.
- **New helper introduced?**: `rowAction(for:)` — a small pure classifier extracted for testability + SRP (the row had inline state lists). Not a duplicate; replaces the buggy inline `isPending`-drives-pill logic.
- **iOS UI only — mobile-ios-design**: consulted. HIG: a control's label must match its action — "Resume" implies returning to an in-progress task; review/processing states get a distinct label + (for processing) a non-actionable status treatment.

## Out of scope
- The "Pending" filter membership (RECORDING/PAUSED aren't in any filter today — they show under "All"); the dashboard's `resumableSection` is the primary resume surface. Noted, not changed here.
- #277 (the stuck-PROCESSING bug that produced the misleading state in the first place) — separate PR.

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -destination 'iPhone 17' -only-testing:AurionTests/SessionsInboxActionTests` → green.
2. CI build matrix.

## Security implications
None. No PHI/audit/secret/AI/consent path. `adoptSession` is the existing, audited resume flow (re-engages capture; the backend already logged `consent_confirmed` when the session started). No new network surface.
