# Plan — bug-277 (iOS defense-in-depth half)

## Task
#277 — iOS side: the processing screen can hang at 95% forever because the Stage 1 wait only falls back to polling when the WebSocket **fails**. A connected-but-silent socket leaves `awaitStage1Ready` suspended indefinitely.

## Why
`awaitStage1Ready` is sequential: `if await subscription.waitForReady() { return }` THEN poll. `waitForReady()` suspends on a `CheckedContinuation` that only resolves on the `stage1_delivered` frame or a socket drop. A healthy-but-silent socket (uvicorn pings keep it alive; the backend push was dead — fixed server-side in #290) → the continuation never resolves → the poll never starts → 95% hold. The backend fix (#290) makes the push fire, but iOS must not depend on a single signal: in prod (2 ECS tasks) the WS connect + pipeline can land on different tasks and the push silently no-ops. The backend pipeline is synchronous — the note exists by the time the upload returned 2xx — so a poll backstop resolves immediately.

## Approach
Rewrite `awaitStage1Ready` to **race** the WS push against the REST poll (`withTaskGroup`, first-to-see-the-note wins) instead of gating the poll on WS failure. Critical detail: when the poll wins, resolve the WS subscriber's `CheckedContinuation` via `subscription.cancel()` BEFORE the group drains — otherwise the suspended WS child never completes and `withTaskGroup` deadlocks. `Stage1WSSubscriber` is `@MainActor` (∴ Sendable) and `SessionManager` is `@MainActor`, so the race is concurrency-safe. The poll keeps its 2s initial cadence, which doubles as the WS's head-start: when the push works (now that #290 wires it) the WS wins in <2s → no poll GET, no fallback audit (happy path preserved). No wall-clock cap (preserves the PR #245 no-false-fail principle) — both paths return only on the real note or Task cancellation. `stage1_ws_fallback_to_poll` now fires when the **poll** delivered (the WS didn't), which is more accurate than the old "WS task ended" trigger.

Files: `ios/Aurion/Aurion/Session/SessionManager.swift` (rewrite `awaitStage1Ready`, extract `pollStage1UntilReady`).

## Acceptance criteria
- [ ] AC-1: app builds iPhone 17 + iPad Pro 11" (M4) — CI (the change is concurrency-structural; the build is the primary gate).
- [ ] AC-2: `awaitStage1Ready` no longer gates the poll on WS failure — it starts a poll child concurrently with the WS wait (diff inspection + the no-deadlock structure: loser's continuation resolved via `subscription.cancel()`).
- [ ] AC-3: existing SessionManager / Stage 1 tests still pass (no regression to the happy path or retry path).
- [ ] AC-4 (manual): with the WS silent, the processing screen advances to the note within ~2s of upload 2xx instead of hanging at 95%.

## DRY / SOLID check
- **Existing helpers to reuse**: `subscription.waitForReady()` / `subscription.cancel()` (existing), `api.getStage1Note` (existing poll call), the existing `stage1_ws_fallback_to_poll` audit, `fetchNote()` (unchanged — still the canonical read after the wait).
- **New helper introduced?**: `pollStage1UntilReady(sessionId:)` — extracted from the existing inline poll loop (not new behavior; relocated so it can be a task-group child). Justified by the race restructure.
- **iOS UI only — mobile-ios-design**: n/a (no UI; async control-flow fix).

## Out of scope
- The backend push wiring (#290 — separate, already open).
- Multi-task WS routing (shared pub/sub) — backend follow-up; this iOS change makes the client resilient to it regardless.

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -destination 'iPhone 17' -only-testing:AurionTests` (or a SessionManager-scoped subset) → green; full CI matrix.
2. Diff inspection: poll runs concurrently with the WS wait; loser's continuation is resolved (no leak/deadlock).

## Security implications
None. No PHI/secret/AI/consent path. `getStage1Note` is the existing authenticated GET. The audit event already exists. Preserves the no-false-fail-deadline privacy/UX principle from PR #245.
