# Plan — issue-295

## Task
#295 — `SessionsInboxView.loadSessions()` injects four fabricated `demo-1..4` sessions on ANY fetch error. In production a network failure shows fake clinical sessions with no error indicator.

## Why
Fabricated sessions on a real device are misleading and risky (they look like real patient encounters). The inbox must show an explicit error + retry, never invent data.

## Approach
- Remove the demo-data fabrication from the `catch`.
- Add `@State private var loadFailed`; set it `true` on error (and `sessions = []`), reset `false` on success.
- Add an error branch to the body (before the generic empty state) shown when `loadFailed && sessions.isEmpty`: an `EmptyStateView` (error icon) + a Retry button calling `loadSessions()`. A failed *refresh* that still has cached sessions keeps showing the list (error gated on `sessions.isEmpty`).
- New localized strings `sessions.loadFailed.title` / `.subtitle` (EN + FR); reuse `common.retry`.

Files: `ios/Aurion/Aurion/Session/SessionsInboxView.swift`, `Resources/{en,fr}.lproj/Localizable.strings`.

## Acceptance criteria
- [ ] AC-1: `loadSessions()` no longer fabricates `demo-*` sessions on error — diff inspection.
- [ ] AC-2: on fetch error with no cached sessions, the inbox shows an error state with a working Retry (not a fake list).
- [ ] AC-3: a failed refresh with existing sessions keeps the list (no flash to error).
- [ ] AC-4: new strings resolve in EN and FR (parity).
- [ ] AC-5: app builds iPhone 17 + iPad Pro 11" (M4).

## DRY / SOLID check
- **Reuse**: `EmptyStateView` (existing), `common.retry` string, the existing `loadSessions()` for retry. No new component.
- **SRP**: view-state only; no business logic added.

## Out of scope
- The pre-existing hardcoded-English empty-state/filter strings (tracked in #298) — only the NEW error strings are localized here.
- Preview/dev seed data: removed from the runtime path; SwiftUI previews can inject via a sample array if needed later (not added now).

## Test plan (executable)
1. Diff: catch sets `loadFailed = true; sessions = []` (no demo rows).
2. `xcodebuild build -scheme Aurion -destination 'iPhone 17'` → BUILD SUCCEEDED (CI runs iPad).
3. Grep: `grep -n "demo-" SessionsInboxView.swift` → no matches.

## Security implications
PRIVACY/SAFETY-positive — stops presenting fabricated sessions as real on network failure. No new PHI/secret/AI path; demo strings carry no patient data.
