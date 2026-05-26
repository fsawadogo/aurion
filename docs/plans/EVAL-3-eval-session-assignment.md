# Plan — EVAL-3 eval session assignment

## Task

`EVAL-3` — admin assigns specific eval sessions to specific EVAL_TEAM (or
ADMIN) members; eval list is filtered by assignment for EVAL_TEAM users.

## Why

Closes the assignment gap left after PRs #14 + #15 (eval triad slices 1 + 2).
Per `web-portal-spec.md` §Feature 7 — *"Session assignment: admin assigns
sessions to specific eval team members."* At pilot scale (3 admins + 0
dedicated eval-team users) this is coordination scaffolding rather than
hard gating, but the audit-log line and the UI affordance are what the
clinical safety committee will look for in the eval interface.

## Approach

### Backend
- New DB table `eval_assignments` (one row per assignment; latest wins):
  - `id` UUID PK
  - `session_id` UUID FK → sessions (unique — one open assignment per session)
  - `assignee_user_id` UUID FK → users
  - `assigned_by` UUID FK → users
  - `assigned_at` timestamptz
  - `completed_at` timestamptz NULL (set when the assignee submits a score)
- Alembic migration `0005_eval_assignments.py`
- New `eval_repo.upsert_assignment` / `eval_repo.delete_assignment` /
  `eval_repo.get_assignment_by_session` / `eval_repo.get_assignments_for_user`
  (mirrors the existing `upsert_score` pattern)
- Endpoints in `backend/app/api/v1/admin/eval.py`:
  - `POST /admin/eval/sessions/{id}/assign` (ADMIN only)
    body: `{"assignee_email": "..."}`
  - `DELETE /admin/eval/sessions/{id}/assign` (ADMIN only)
  - `GET /admin/eval/assignees` (ADMIN only) — list users with role
    EVAL_TEAM or ADMIN (eligible assignees)
- Extend list endpoint `GET /admin/eval/sessions`:
  - If caller role is EVAL_TEAM: filter to sessions assigned to them
  - If caller role is ADMIN: return all sessions (assignment irrelevant)
- Extend `EvalSessionResponse` + `EvalSessionDetailResponse` with
  `assigned_to: Optional[str]` (assignee email, or null)
- `submit_eval_score` sets `completed_at` on the open assignment row
  (if one exists) — closes the assignment on score submission

### Frontend
- Web list page (`/eval`): new column "Assigned to" showing email or "—"
- Web detail page (`/eval/[id]`): if the current user is ADMIN, show an
  "Assigned to" dropdown that lists `getEvalAssignees()` and POSTs the
  selection; if not ADMIN, show static text
- `lib/api.ts`: `assignEvalSession`, `unassignEvalSession`,
  `getEvalAssignees`

## Acceptance criteria

- [ ] AC-1: `POST /admin/eval/sessions/{id}/assign` with
  `{"assignee_email": "uzziel.tamon@aurionclinical.com"}` (as ADMIN)
  creates an `eval_assignments` row, returns the updated
  `EvalSessionResponse` with `assigned_to: "uzziel.tamon@aurionclinical.com"`,
  and emits an `eval_assignment_created` audit event. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_assign_session`.
- [ ] AC-2: As an EVAL_TEAM user not assigned to session X,
  `GET /admin/eval/sessions` excludes session X. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_eval_team_sees_only_assigned`.
- [ ] AC-3: As ADMIN, `GET /admin/eval/sessions` includes all
  sessions regardless of assignment. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_admin_sees_all_sessions`.
- [ ] AC-4: `DELETE /admin/eval/sessions/{id}/assign` as ADMIN removes
  the row and the session's `assigned_to` becomes `None`. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_unassign_session`.
- [ ] AC-5: When the assignee submits a score via
  `POST /admin/eval/sessions/{id}/score`, the assignment's `completed_at`
  is set. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_score_completes_assignment`.
- [ ] AC-6: `GET /admin/eval/assignees` as ADMIN returns the list of
  users with EVAL_TEAM or ADMIN role. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_list_assignees`.
- [ ] AC-7: A non-ADMIN call to any of the three assignment endpoints
  returns 403. Verified by
  `pytest backend/tests/unit/test_eval_admin_sessions.py::test_clinician_cannot_assign`.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - `require_role(UserRole.ADMIN)` — already gates admin-only routes
  - `get_session_or_404` — session lookup with 404 boundary
  - `write_audit` — single helper for audit events
  - `users_repo.get_by_id` / `users_repo.get_by_email` — user lookup
  - `eval_repo.upsert_score` — pattern mirrored for `upsert_assignment`
- **New helper introduced?**: Yes — `eval_repo.upsert_assignment` and
  3 related queries. Justified: this is the **third** repository
  module in the codebase (note_gen, users, eval) and assignment is a
  distinct entity from scores. No premature abstraction.
- **iOS UI tasks only**: N/A — this is backend + web.

## Out of scope

- Multi-reviewer (right now: one open assignment per session)
- Re-assignment history (only the latest assignment row is preserved;
  audit log retains the trail)
- Frontend assignment-dropdown on the **list** page (only on detail —
  list shows the current assignee as a read-only column)
- Web Cognito hosted UI integration (separate task `WEB-COGNITO-UI`)
- Notifications when assigned (Slack DM / email — separate concern)

## Test plan (executable)

1. `cd backend && python3 -m pytest tests/unit/test_eval_admin_sessions.py -v`
   (expect the 7 AC tests to pass, plus the existing eval list/detail/score
   tests to stay green)
2. `cd backend && python3 -m pytest tests/unit/ -q`
   (expect the full unit suite — 228 + the new tests — to pass)
3. `cd web && npx next lint` (expect 0 errors)
4. CI's `build` + `lint` + `test` jobs must turn green on the PR

## Security implications

- New endpoints all gated `require_role(UserRole.ADMIN)`; non-admins
  receive 403 (AC-7).
- Audit events `eval_assignment_created` / `eval_assignment_removed` /
  `eval_assignment_completed` extend `AuditEventType` enum (Q-01 pattern).
  No update or delete operations on existing audit rows.
- Assignment row stores `assignee_user_id` (FK to users.id), not the
  email — no PHI risk.
- `GET /admin/eval/assignees` returns email + display_name only; same
  shape as the existing admin users list (`UserResponse`) so no new
  surface area.
- No new AI calls, no PHI in logs/errors/responses.
