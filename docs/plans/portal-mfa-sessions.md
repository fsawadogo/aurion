# Portal MFA setup + active sessions (issue #163)

## Task
#163 — Portal MFA setup + active sessions on `/portal/profile/account`.

## Why
The clinician portal Security card on `/portal/profile/account` (PR #154)
currently ships with the placeholder copy:

> Multi-factor authentication and active-session management are coming
> in a follow-up. For now you can sign out below — your session ends
> immediately on this device.

The follow-up has to land before the CREOQ/CLLC pilot so two pilot-blocker
items resolve in one PR:

* **AUR-COG-MFA-RESTORE** memory — dev pool MFA was forced OFF to unblock
  the iOS native-login bring-up; we need a usable self-serve enrollment
  flow before pilot.
* Issue #163 explicitly lists MFA enroll/disable, active-session listing,
  and "sign out everywhere" as the missing portal surface.

The issue body still references Cognito attributes (`MFA_REQUIRED`,
`AdminUserGlobalSignOut`). PR #234 (auth pivot, 2026-06-04) replaced
that path with backend-issued JWT + TOTP + refresh tokens:

* MFA lives in `users.mfa_secret_encrypted` / `users.mfa_enrolled_at`
  with the `/api/v1/auth/mfa/setup` + `/api/v1/auth/mfa/setup/verify`
  endpoints already shipped.
* "Active sessions" are rows in the `refresh_tokens` table from
  PR #234 — every login or rotation persists one hashed row.
* The work is therefore a thin clinician-scoped wrapper
  (`/me/mfa/*` + `/me/sessions/*`) plus the portal UI, with two
  new columns on `refresh_tokens` so revoke-others-but-keep-me works.

## Approach

### Backend
Add a new router file `backend/app/api/v1/me_security.py` (keep `me.py`
from sprawling further; it is already 1754 lines). The router prefix
stays `/me` so the URLs read `/api/v1/me/mfa/...` and
`/api/v1/me/sessions/...`. Mount in `app/main.py` alongside the
existing me routers. Endpoints:

* `GET /me/mfa/status` — `{enrolled, last_verified_at}` for the card
  header. Reads `UserModel.mfa_enrolled_at` and the new
  `mfa_last_verified_at` column added by this PR.
* `POST /me/mfa/enroll` — generate a fresh TOTP secret + 8 base32
  recovery codes. Returns `{provisioning_uri, secret, recovery_codes,
  setup_token}`. The secret + hashed recovery codes are wrapped into
  a 5-minute signed `setup_token` (JWT, signed with the existing
  `AUTH_JWT_SIGNING_KEY`); nothing persists yet. The clinician must
  successfully verify a code before the secret sticks.
* `POST /me/mfa/verify-enroll` — body `{setup_token, code}`. Decodes
  the setup_token, validates the TOTP code, persists
  `mfa_secret_encrypted` (KMS), `mfa_recovery_codes_hashed`, and
  `mfa_enrolled_at`. Emits `MFA_ENROLLED`.
* `DELETE /me/mfa` — body `{current_code}`. Validates TOTP, clears
  the secret + recovery codes + `mfa_enrolled_at`. Emits `MFA_DISABLED`.
* `GET /me/sessions` — lists this clinician's refresh-token rows
  (filter `user_id == current.user_id`, `revoked_at IS NULL`,
  `expires_at > now()`). Each row: `{id, device_hint, ip_class,
  created_at, last_used_at, is_current}`. `is_current` is derived
  from the access token's JTI -> refresh row id link added by this PR.
* `POST /me/sessions/{id}/revoke` — set `revoked_at = utcnow()` on
  the named row IFF `user_id == current.user_id`. Emits
  `SESSION_REVOKED`.
* `POST /me/sessions/revoke-all` — revoke every active refresh row
  for the current user EXCEPT the one used to make this call. Emits
  `SESSIONS_REVOKED_ALL`.

### Schema
Alembic migration `0031_mfa_recovery_and_session_metadata`:
* `users.mfa_recovery_codes_hashed JSONB` — list of bcrypt hashes,
  default `NULL`.
* `users.mfa_last_verified_at TIMESTAMPTZ` — last successful TOTP
  verification, default `NULL`. Updated by every successful
  `/auth/mfa/verify-login` and `/me/mfa/verify-enroll` call.
* `refresh_tokens.device_hint VARCHAR(64)` — derived UA fingerprint
  (e.g. `"Safari · macOS"`), default `NULL`. Set on token mint;
  NEVER stores the raw User-Agent.
* `refresh_tokens.last_used_at TIMESTAMPTZ` — updated on every
  `/auth/refresh` call, default `NULL`.
* `refresh_tokens.access_token_jti UUID` — the JTI the most recent
  access token was minted with for this refresh row. Lets
  `/me/sessions` flag `is_current=True` for the row that matches the
  JTI in the bearer token of the caller. Updated atomically with
  `last_used_at`.

### Web portal
* `web/components/portal/MfaCard.tsx` — header (status pill), enroll
  button when not enrolled, disable button + "last verified" timestamp
  when enrolled, opens `MfaEnrollModal` / `MfaDisableModal`.
* `web/components/portal/MfaEnrollModal.tsx` — two-step modal:
  step 1 shows the QR code (rendered with a small inline QR encoder
  — no dependency added) + the secret string + the 8 recovery codes
  with a copy button; step 2 takes a TOTP code and calls
  `verifyMfaEnroll`. The recovery codes are stored only in component
  state, never re-fetched.
* `web/components/portal/SessionsCard.tsx` — table of sessions with
  device hint, ip class, last-used, current-session badge, per-row
  revoke button, and a "Sign out everywhere" CTA.
* `web/app/portal/profile/account/page.tsx` — replace the placeholder
  Security card with `<MfaCard />` + `<SessionsCard />`.
* `web/lib/portal-api.ts` — typed helpers
  `getMfaStatus / enrollMfa / verifyMfaEnroll / disableMfa /
  listSessions / revokeSession / revokeAllSessions`.
* `web/messages/{en,fr}.json` — strings under `Account.mfa.*` and
  `Account.sessions.*`. Quebec French per the project memory.

### New audit events
Added to `app/core/audit_events.py`:
* `MFA_DISABLED` — `{actor_id}`.
* `SESSION_REVOKED` — `{actor_id, token_id}`.
* `SESSIONS_REVOKED_ALL` — `{actor_id, count}`.

`MFA_ENROLLED` already exists from the auth-pivot and is reused.

### Subagent assignments
Single lane (`lane-web/portal-mfa-sessions`). Backend + web + tests
all in this PR.

## Acceptance criteria
- [ ] AC-1: `GET /api/v1/me/mfa/status` returns
  `{enrolled: bool, last_verified_at: ISO8601 | null}`. Verified by
  `tests/integration/test_me_security_mfa.py::test_status_unenrolled`.
- [ ] AC-2: `POST /api/v1/me/mfa/enroll` returns
  `{qr_uri, secret, recovery_codes[8], setup_token}` without
  mutating the user row. Verified by
  `test_me_security_mfa.py::test_enroll_does_not_persist`.
- [ ] AC-3: `POST /api/v1/me/mfa/verify-enroll` with a valid
  `setup_token` + code persists the encrypted secret, hashed recovery
  codes, and marks `mfa_enrolled_at`. Audit `MFA_ENROLLED` written.
  Verified by `test_me_security_mfa.py::test_verify_enroll_persists`.
- [ ] AC-4: `DELETE /api/v1/me/mfa` requires a fresh TOTP code and
  clears all three columns. Audit `MFA_DISABLED` written. Verified
  by `test_me_security_mfa.py::test_disable_requires_code`.
- [ ] AC-5: `GET /api/v1/me/sessions` returns only the caller's own
  refresh rows, each carrying `device_hint`, `ip_class`,
  `created_at`, `last_used_at`, `is_current`. Verified by
  `test_me_security_sessions.py::test_only_returns_own`.
- [ ] AC-6: `POST /api/v1/me/sessions/{id}/revoke` revokes a row
  owned by the caller and 404s a row belonging to someone else.
  Audit `SESSION_REVOKED` written. Verified by
  `test_me_security_sessions.py::test_revoke_own_and_other`.
- [ ] AC-7: `POST /api/v1/me/sessions/revoke-all` revokes every
  active row for the caller EXCEPT the one used to make the call.
  Audit `SESSIONS_REVOKED_ALL` written. Verified by
  `test_me_security_sessions.py::test_revoke_all_keeps_current`.
- [ ] AC-8: Portal account page renders `<MfaCard />` with the
  enrolled / not-enrolled split + the two-step enroll modal QR-code
  flow. Verified by `web/tests/MfaCard.spec.tsx`.
- [ ] AC-9: Portal account page renders `<SessionsCard />` with
  per-row revoke + "Sign out everywhere" CTA. Verified by
  `web/tests/SessionsCard.spec.tsx`.
- [ ] AC-10: EN + FR strings present under `Account.mfa.*` and
  `Account.sessions.*`. Verified by an i18n parity assertion in
  `web/tests/MfaCard.spec.tsx`.
- [ ] AC-11: All `/me/security/*` endpoints role-gate to the calling
  user — a clinician cannot read or revoke another user's sessions
  (404), and `get_current_clinician` enforces CLINICIAN role.
  Verified by `test_me_security_sessions.py::test_only_returns_own`
  + the existing 403 contract on `get_current_clinician`.

## DRY / SOLID check
- **Existing helpers reused**:
  * `write_audit` (`backend/app/api/v1/_helpers.py`) — every audit
    emission goes through this single wrapper, not the
    audit service directly.
  * `get_current_clinician` (`backend/app/api/v1/me.py`) — the
    CLINICIAN-only auth dependency every `/me/*` route already
    composes.
  * `app.modules.auth.totp.{generate_secret, provisioning_uri,
    verify_code}` — the thin pyotp wrapper. The new endpoints
    DO NOT reach for pyotp directly.
  * `app.core.kms_encryption.{encrypt_str, decrypt_str}` — for the
    TOTP secret persistence. Same shape as `/auth/mfa/setup`.
  * `app.modules.auth.jwt_tokens.hash_refresh_token` — to look up
    the caller's refresh row from the access-token JTI link.
  * `app.modules.auth.passwords.hash_password / verify_password` —
    reused for hashing recovery codes (bcrypt is already in deps;
    introducing a new hasher would violate DRY).
  * `app.modules.audit_log.service.get_audit_log_service` — already
    wrapped by `write_audit`.
  * Web: `fetchWithAuth` from `web/lib/api.ts`; `Modal`, `Card`,
    `Button` from `web/components/ui/`; `withIntl` test helper.
- **New helper introduced?**: One — `device_hint_from_user_agent`
  in `backend/app/modules/auth/device_hint.py`. Lives there because
  two call sites (login + refresh) plus `/me/sessions` all need the
  same derivation; introducing it here keeps the rule single-sourced.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a — this
  lane is web + backend only. The iOS MFA UI is explicitly OUT OF
  SCOPE (separate iOS PR).

## Out of scope
- iOS MFA enrollment UI — a separate iOS PR will consume the same
  `/me/mfa/*` endpoints.
- Self-serve recovery-code regeneration after exhaustion — clinician
  contacts admin, who can clear MFA via the existing
  `DELETE /api/v1/auth/mfa` endpoint.
- Admin-mode "force MFA on for other users" — separate admin tooling.
- Cognito sign-out / `AdminUserGlobalSignOut` — pre-pivot artifact;
  the issue body is stale and this PR uses the new refresh-token
  surface.
- Geo-IP enrichment on `ip_class` beyond `local | private | internet`.
  Anything richer is PHI-adjacent and out of scope for the pilot.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/integration/test_me_security_mfa.py tests/integration/test_me_security_sessions.py -v`
2. `cd backend && python3 -m alembic upgrade head` should succeed
   against a fresh dev DB.
3. `cd web && npx vitest run tests/MfaCard.spec.tsx tests/SessionsCard.spec.tsx`
4. Manual: log in as `clinician-test@aurionclinical.com` → portal →
   `/portal/profile/account` → enroll MFA → log out → log back in →
   MFA challenge fires → succeeds.
5. Manual: open the portal in two browsers as the same clinician →
   revoke browser B's session from browser A → browser B's next
   request 401s and bounces to `/login`.

## Security implications
- **MFA secrets**: KMS-encrypted at rest (`mfa_secret_encrypted`,
  existing column). Setup-token JWTs carry the secret only for the
  5-minute enrollment window and are signed with
  `AUTH_JWT_SIGNING_KEY`. Plaintext secret never logged.
- **Recovery codes**: 8 codes generated server-side, hashed with
  bcrypt before persistence (`mfa_recovery_codes_hashed`). Plaintext
  returned to the client EXACTLY ONCE in the enroll response — never
  re-fetchable.
- **Refresh-token sensitivity**: revoke is a hard
  `revoked_at = utcnow()` write (no soft-delete column). Next request
  on a revoked token returns 401 immediately because the existing
  `_find_active_refresh_row` already filters
  `revoked_at IS NULL`. Raw tokens never appear in any API response
  outside the token-issuance path; the per-session rows in
  `GET /me/sessions` carry only the row UUID, never the token hash.
- **Device hint**: derived from the User-Agent (browser family +
  platform family, max 64 chars). Strips PHI/exact-version detail.
  Stored in plaintext because it is not PHI and is the only signal a
  clinician has when deciding which session to revoke.
- **IP class**: derived (`local` / `private` / `internet`) — never
  the raw IP. Same PHI-aware design as `issued_ip_hash`.
- **Audit events**: every state change emits a row.
  `MFA_DISABLED / SESSION_REVOKED / SESSIONS_REVOKED_ALL` added to
  the kwarg whitelist; no PHI in kwargs.
- **No PHI**: routes are auth surface only; never touch session /
  transcript / note tables.
- **Rate limiting**: TOTP + recovery-code verify failures are NOT
  yet rate-limited here — that's part of the existing
  `lockout.record_failure` flow on `/auth/mfa/verify-login`. The new
  `/me/mfa/verify-enroll` and `DELETE /me/mfa` are authenticated
  routes (Bearer token required) and benefit from the access-token
  short TTL, so brute-force surface is bounded by login lockout
  anyway. A dedicated /me/mfa rate limit can be a P1 follow-up.
