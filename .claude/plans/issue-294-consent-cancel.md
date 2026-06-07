# Plan — issue-294

## Task
#294 — The consent overlay's **Cancel** button (`Capture/CaptureView.swift:630`) has an empty action `Button(L("common.cancel")) {}`. Tapping it does nothing, so the clinician can't back out of the consent gate once it appears.

## Why
A consent-gated screen must offer a real exit. The session is created (`session_created` audit) and sits in `CONSENT_PENDING` when the overlay shows; Cancel should abort it and return to the dashboard. Same dead-button class as #274.

## Approach
Wire Cancel to `sessionManager.endSession()` — the established abort/teardown path (used for "review dismissed, crash recovery discard, etc."): it tears down the live transcriber, stops screen capture, ends the Live Activity, drops the on-disk WAV, clears the session, and sets `uiState = .idle` (which routes `ContentView` back to the dashboard). Add a light haptic to match the app's other dismiss actions.

Files: `ios/Aurion/Aurion/Capture/CaptureView.swift`.

## Acceptance criteria
- [ ] AC-1: the consent Cancel button calls `sessionManager.endSession()` (no longer an empty closure) — diff inspection.
- [ ] AC-2: app builds iPhone 17 + iPad Pro 11" (M4).
- [ ] AC-3 (manual): start a session → consent overlay → Cancel → returns to dashboard, no recording started, session cleared.

## DRY / SOLID check
- **Reuse**: `sessionManager.endSession()` (the existing abort path — same method the other cancel/dismiss flows use), `AurionHaptics.impact`. No new method.
- **SRP**: view calls the manager's teardown; no business logic added to the view.

## Out of scope
- Backend discard of the abandoned `CONSENT_PENDING` session (no PHI, no consent given; a cleanup-sweep concern) — note as a follow-up.
- A `consent_cancelled` audit event — deferred; `endSession` is local teardown and the session never advanced past `session_created`.

## Test plan (executable)
1. Diff: Cancel action calls `endSession()`.
2. `xcodebuild build -scheme Aurion -destination 'iPhone 17'` → BUILD SUCCEEDED (CI runs iPad).
- Note: SwiftUI button-action wiring isn't unit-testable without a UI-test host (none in-project); same posture as #274.

## Security implications
PRIVACY-positive — Cancel now actually aborts a consent-pending session and drops any staged WAV via `endSession`. No new PHI/secret/AI path. Consent gate unchanged (recording still hard-blocked until `confirmConsent`).
