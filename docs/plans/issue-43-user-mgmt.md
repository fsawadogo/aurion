# Plan for #43 — F1 User Management Backend (+ #44 frontend, + web JWT-login switch)

## Task
**#43** — F1 User Management Backend: enforce account deactivation, plus the
frontend fix (#44) and a web-portal JWT-login switch that pauses the Cognito
hosted UI for local-dev usability.

## Why
CLAUDE.md §"Non-Negotiable Technical Rules" requires auth to be enforceable.
The Cognito JWT path is **stateless** — `_validate_cognito_jwt` builds
`CurrentUser` from claims only, so flipping `is_active=false` in the DB had
no teeth. Issue #43's AC explicitly says "Deactivate accounts (immediate
Cognito disable)". We achieve the *intent* (immediate request-level
blocking) without an admin Cognito call by enforcing `is_active` inside
`get_current_user`. The Cognito-side `AdminDisableUser` + `GlobalSignOut`
remain as a defense-in-depth follow-up.

The web JWT-login switch rides in the same PR because both changes are
auth-adjacent, both are local, and shipping them together avoids two near-
identical CI cycles. Cognito hosted UI was wired (PR #28-30) but blocks
local-dev usability (no local Cognito; needs the real dev pool password).
The backend's `/api/v1/auth/login` endpoint (seeded `_DEV_USERS`) already
returns a backend-signed token; we just point the login page at it.

## Approach
- **`backend/app/modules/auth/service.py`** — inject `db: AsyncSession =
  Depends(get_db)` into `get_current_user`. Add `_ensure_active(db, user_id)`
  helper: query `UserModel.is_active` by sub; 403 if False; allow if None
  (first-login provisioning). Only runs on the non-local Cognito path —
  local dev tokens skip it because seeded users are always active.
- **`backend/tests/unit/test_auth_active.py`** — three tests pinning the
  three branches (False → 403, True → pass, None → pass).
- **`web/types/index.ts`** — extend `UpdateUserPayload` with `is_active?:
  boolean` so the API client can carry the flag.
- **`web/app/users/page.tsx`** — replace the no-op
  `handleDeactivate({role: undefined})` with `handleSetActive(id, active)`
  calling `updateUser(id, {is_active: active})`. Render
  Deactivate (red) when active, Activate (emerald) when inactive. Add
  `window.confirm` guard on deactivate.
- **`web/app/(auth)/login/page.tsx`** — native email + password form against
  `lib/api.login` (POST `/api/v1/auth/login`). Premium navy/gold styling
  reused. "Local dev credentials" `<details>` panel surfaces the seeded
  users when `NEXT_PUBLIC_API_URL` points at localhost. Friendlier error
  surfacing for the two common local failures (backend unreachable, 404 in
  non-local).
- **`web/lib/api.ts`** — `logout()` becomes session-aware: if there's a
  Cognito id_token in storage, route through `cognitoSignOut`; otherwise
  clear `aurion_token` and bounce to `/login`. Native sessions stop getting
  redirected through Cognito's `/logout`.

## Acceptance criteria
- [ ] **AC-1**: Inactive user (DB `is_active=false`) → 403 on next request,
      verified by `pytest tests/unit/test_auth_active.py::TestEnsureActive::test_deactivated_user_is_blocked`
- [ ] **AC-2**: Active user passes, verified by `…::test_active_user_passes`
- [ ] **AC-3**: Not-yet-provisioned user (no row) → pass, verified by
      `…::test_unprovisioned_user_passes`
- [ ] **AC-4**: Web "Deactivate" button now actually PATCHes `is_active=false`
      and "Activate" reverses, verified by browsing `/users` against the
      local backend
- [ ] **AC-5**: Backend pytest suite stays green (existing 276 → 279
      passing), verified by `cd backend && python3 -m pytest -q`
- [ ] **AC-6**: `cd web && npm run build` succeeds (Next compiles `/users`
      and `/login` clean), verified by exit 0
- [ ] **AC-7**: Native JWT login round-trip works against local backend,
      verified by `curl -X POST localhost:8080/api/v1/auth/login` + `GET
      /auth/me` with the returned token

## DRY / SOLID check
- **Existing helpers reused**: `Depends(get_db)`, `select()`, `UserModel`,
  `HTTPException(403, …)`, `updateUser` from `lib/api.ts`, the same
  `getStoredIdToken` already imported by `api.ts` (for `logout` branching).
- **New helper introduced?** `_ensure_active` — yes, but single-purpose,
  one call site, isolated for unit testing. Not a third copy of a pattern;
  a clean extraction for clarity.
- **SRP**: `get_current_user` still does one thing (resolve + authorize);
  `_ensure_active` does one thing (DB activation gate).
- **DIP**: DB session injected, not constructed inside.

## Out of scope (deferred to follow-ups)
- True Cognito-side `AdminDisableUser` + `AdminUserGlobalSignOut`
  (defense-in-depth; needs boto3 + IAM via Terraform). Follow-up issue
  will be opened post-merge.
- DELETE `/admin/users/{id}` endpoint — PATCH `is_active=false` already
  covers soft-delete.
- "Reset access / force re-auth" — same Cognito hardening follow-up.
- Restoring Cognito hosted UI as the default login path. `lib/cognito.ts`
  stays intact so flipping back later is a one-component change in
  `app/(auth)/login/page.tsx`.

## Test plan (executable)
1. `cd backend && ruff check app/modules/auth/service.py tests/unit/test_auth_active.py` → All checks passed
2. `cd backend && python3 -m pytest tests/unit/test_auth_active.py tests/unit/test_admin_users.py -q` → 12 passed
3. `cd backend && python3 -m pytest tests/unit/ -q` → 276 → 279 passed (no regressions)
4. `cd web && npm run build` → exit 0, `/users` + `/login` in route manifest
5. `docker-compose up -d --no-deps aurion-api && curl -fs localhost:8080/health` → 200
6. `curl -X POST localhost:8080/api/v1/auth/login -H "Content-Type: application/json" -d '{"email":"admin@aurionclinical.com","password":"admin"}'` → returns access_token + role=ADMIN
7. `curl -H "Authorization: Bearer <token>" localhost:8080/api/v1/auth/me` → returns the admin user

## Security implications
- **Auth path hardened**: a deactivated user with a still-valid Cognito
  token can no longer act. Closes a real authz gap (immediate intent of
  #43's AC).
- **No PHI introduced**: helper logs nothing (no email, no role); 403
  message reads "Account deactivated. Contact your administrator."
- **Audit log untouched**: deactivation already audits via `USER_UPDATED`
  in the PATCH route.
- **Adds 1 DB query per authenticated request** (non-local). FastAPI
  per-request dependency cache reuses the request's session — no extra
  connection. For 3-5 pilot clinicians, latency impact is negligible.
- **JWT login switch**: backend `/auth/login` is gated `_APP_ENV == "local"`
  (returns 404 otherwise). Cannot be used against a non-local backend, so
  shipping the web change is safe even if `NEXT_PUBLIC_API_URL` later
  points at api-dev/prod (login would 404, user falls through to the error
  banner). `lib/cognito.ts` is unchanged; restoration is a one-line
  component swap.
