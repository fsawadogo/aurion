# Plan — bug-279

## Task
#279 — Dashboard header "0 sessions today" always shows 0; bare `ISO8601DateFormatter` in `todayCount` rejects the backend's fractional-seconds timestamps.

## Why
The backend serializes `created_at` via `datetime.isoformat()` → `2026-06-06T17:04:21.690+00:00`. A default `ISO8601DateFormatter` (`.withInternetDateTime` only) returns nil for fractional seconds, so every session fails the `todayCount` guard → header reads "0 sessions today" even when sessions exist today (the card below it renders the date fine via Theme's fractional-tolerant parser). Pilot physicians see a wrong count on the home screen. CLAUDE.md success criteria depend on accurate session surfacing.

## Approach
DRY extraction (workflow §6c — this is the 3rd copy of the same parse logic):
- `Theme.swift` has `_parseISODate` (fractional → plain fallback), used by `formatRelativeTime`.
- `SessionsInboxView.swift` has its own private `isoFractional`/`isoPlain` pair (2nd copy).
- `DashboardView.todayCount` uses a bare `ISO8601DateFormatter` (3rd site — broken).

Promote `Theme.swift`'s `_parseISODate` to a module-internal free function `parseISODate(_:)`, reuse it in `formatRelativeTime`, `DashboardView.todayCount`, and `SessionsInboxView.inDateRange`; delete the inbox's private formatters.

Files: `ios/Aurion/Aurion/App/Theme.swift`, `App/DashboardView.swift`, `Session/SessionsInboxView.swift`, new `AurionTests/ParseISODateTests.swift`.

## Acceptance criteria
- [ ] AC-1: `parseISODate("2026-06-06T17:04:21.690+00:00")` returns a non-nil Date — verified by `ParseISODateTests.parsesFractionalSeconds`.
- [ ] AC-2: `parseISODate("2026-06-06T17:04:21Z")` (plain, legacy) returns non-nil — `ParseISODateTests.parsesPlain`.
- [ ] AC-3: `parseISODate("not-a-date")` returns nil — `ParseISODateTests.rejectsGarbage`.
- [ ] AC-4: a session created "today" with a fractional timestamp is counted by the same logic `todayCount` uses (test the shared parser + `Calendar.isDateInToday`) — `ParseISODateTests.countsTodayWithFractionalSeconds`.

## DRY / SOLID check
- **Existing helpers to reuse**: `Theme.parseISODate` (newly promoted from `_parseISODate`); `_isoFractionalFormatter` / `_isoPlainFormatter` already live in Theme.swift — single source of truth.
- **New helper introduced?**: No new logic — promoting an existing private fn to internal and deleting two duplicate copies (net −1 duplication). Satisfies the 3rd-copy extraction rule.
- **iOS UI tasks only — mobile-ios-design**: n/a (no UI/layout change; pure data-parse fix).

## Out of scope
- `LivePreviewOverlay.swift` and `EmrWriteBackCard.swift` each carry their own *correct* fractional+plain dual-formatter pair — not broken, so left as a deferred DRY cleanup (collapse onto `parseISODate`) rather than a risk-refactor here.
- `AuditLogger*.swift` use `ISO8601DateFormatter().string(from:)` to *write* timestamps (Date→string), not parse — not the bug class.
- Changing the backend timestamp format.

## Scope note (updated during implement)
Grep for `ISO8601DateFormatter()` surfaced a 4th genuine instance of the same bug: `SessionNoteView.displayDate` parses `session.createdAt` with a bare formatter (note-detail header falls back to the raw ISO string on fractional timestamps). Same one-line fix → included in this PR.

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -only-testing:AurionTests/ParseISODateTests` (CI runs the full matrix).
2. Grep proof: `grep -rn "ISO8601DateFormatter()" ios/Aurion/Aurion/App/DashboardView.swift` → no matches after fix.

## Security implications
None. No PHI, no audit, no secrets, no AI prompt, no consent path. Pure client-side date parsing.
