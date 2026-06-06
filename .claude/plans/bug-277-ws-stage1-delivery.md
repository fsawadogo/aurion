# Plan — bug-277 (backend half)

## Task
#277 — Processing screen hangs at 95% forever. Root cause (backend): `notify_stage1_delivered` is **dead code** — it has zero callers, so the `stage1_delivered` WebSocket event is never broadcast even though the synchronous pipeline reaches `AWAITING_REVIEW` and writes the `STAGE1_DELIVERED` audit row.

## Why
`POST /api/v1/transcription/{id}` runs the whole pipeline synchronously, transitions to `AWAITING_REVIEW`, writes the `STAGE1_DELIVERED` **audit** row, and returns — but never calls `notify_stage1_delivered`. iOS opens `/ws/notes/{id}` and waits for the `stage1_delivered` frame; it never arrives, so the screen holds at 95% (verified: `stage1_ws_fallback_to_poll` has fired 0× in 1073 audit events; six days of logs have zero "Broadcast to session" lines). Masked by the pre-#273 upload crash; surfaced the first successful upload after #273.

## Approach
Backend (this PR):
1. `transcription.py`: capture the note `generate_stage1_note` already returns (`-> Note`, line 757) and, after the `STAGE1_DELIVERED` audit, call `await notify_stage1_delivered(str(session_id), note)`. Defensively wrapped so a WS hiccup can never fail the 200 response.
2. `websocket.py`: harden `notify_stage1_delivered` AND `notify_stage2_delivered` with the same try/except-swallow-and-log posture `notify_stage2_progress` already has (broadcast failure must never propagate into a request).
3. Regression test: a connected fake WS client receives the `stage1_delivered` frame; a failing client is swallowed (no raise) and removed.

iOS half (separate branch, ships in the iOS TestFlight bundle): treat the upload 2xx (which only returns after `AWAITING_REVIEW`) as completion proof and `fetchNote()` directly — keeping the WS as a latency optimization, not the sole signal. Tracked separately so the dispatch bundles into one build.

## Acceptance criteria
- [ ] AC-1: completing Stage 1 broadcasts a `stage1_delivered` event to a connected client — `test_websocket_notify.test_notify_stage1_delivered_reaches_connected_client`.
- [ ] AC-2: a client whose `send_text` raises does NOT propagate out of `notify_stage1_delivered` and is removed — `...test_failing_client_is_swallowed`.
- [ ] AC-3: `notify_stage1_delivered` with no connected clients is a no-op (no raise) — `...test_no_clients_noop`.
- [ ] AC-4: the transcription route calls `notify_stage1_delivered` after the `STAGE1_DELIVERED` audit (import wired; covered by AC-1 mechanism + a grep/inspection).
- [ ] AC-5: backend tests + `docker compose up` + `/health` 200.

## DRY / SOLID check
- **Existing helpers to reuse**: `notify_stage1_delivered`/`manager.broadcast_to_session` (existing, just uncalled), the note already returned by `generate_stage1_note` (no re-read), `write_audit`. The try/except posture mirrors the existing `notify_stage2_progress`.
- **New helper introduced?**: No. Wiring an existing function + hardening two existing functions.
- **SRP/DIP**: route stays HTTP-boundary; the push is a fire-and-forget side effect after the state transition; no business logic moved into the route.

## Out of scope (documented follow-ups)
- **Stage 2 delivery push** (`notify_stage2_delivered`, also caller-less): the merged note isn't available at the vision finalize point (`run_stage2_vision` returns a captions summary; REVIEW_COMPLETE/merge lives elsewhere), and Stage 2 already has `notify_stage2_progress` + iOS `/stage2-status` polling, so it never hung like Stage 1. Hardened here; wiring deferred to a focused follow-up.
- **Multi-task scaling**: `ConnectionManager` is in-process; once the service runs >1 ECS task (prod sets 2), WS connect + pipeline can land on different tasks and the push no-ops. Needs shared pub/sub or sticky routing — flagged for a pre-scale follow-up.
- iOS fetch-after-2xx defense (separate iOS-bundle branch).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_websocket_notify.py -q` → green.
2. `cd backend && python3 -m pytest -q` → suite green (no regression).
3. `docker compose up -d && curl -fs localhost:8080/health` → 200.

## Security implications
No PHI in logs (the broadcast log lines carry session id + counts only; the note payload goes only to the authenticated WS subscriber, never to logs). No new secret/AI/consent path. The push is best-effort and cannot alter the request's success/audit outcome. Audit log remains append-only (no new write paths).
