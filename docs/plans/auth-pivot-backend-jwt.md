# AUTH-PIVOT-BACKEND — Backend foundation slice

## Task

`AUTH-PIVOT-BACKEND` — drop Cognito entirely. Standardize on backend-issued JWT + TOTP + email-link password reset. Backend takes ownership of every auth state change.

## Why

CTO decision: Cognito hosted UI is being removed across iOS and the web portal. The `APP_ENV=local`-only `/auth/login` path in `backend/app/api/v1/auth.py` becomes the production path. Backend owns TOTP MFA (no more `SOFTWARE_TOKEN_MFA` via Cognito) plus dual password-reset flows: admin-issued temp passwords AND self-serve email link via SES. PR #233 (iOS Cognito TOTP) was closed superseded; the SwiftUI work rebases onto this backend in a follow-up iOS PR. This PR is the backend foundation slice only.

## Approach

A single new `app/modules/auth/` surface with four siblings to the existing `passwords.py` + `service.py`:

* `jwt_tokens.py` — `mint_access_token`, `mint_refresh_token`, `verify_access_token`. HS256. Signing key from `AUTH_JWT_SIGNING_KEY` (Secrets Manager). Access TTL 30m, refresh TTL 30d. Refresh tokens are 256-bit URL-safe base64 strings; only the SHA-256 hash is stored.
* `totp.py` — `generate_secret`, `provisioning_uri`, `verify_code` (drift ±1 for 30s clock skew). `pyotp` backed. URI: `otpauth://totp/Aurion:<email>?secret=<base32>&issuer=Aurion`.
* `password_reset.py` — `issue_reset_token`, `verify_reset_token`. 24h TTL, one-time use (set `consumed_at`).
* `lockout.py` — `record_failure`, `is_locked`, `record_success`. 5 failures → 15 minutes; reset counter on success.
* `email.py` — `send_password_reset_email` via SES; `AUTH_EMAIL_ENABLED=false` logs link at INFO so dev devs copy from the log.

`get_current_user` keeps its `Depends(get_current_user) -> CurrentUser` contract byte-identical so the rest of the API doesn't churn. Implementation swaps Cognito JWKS validation for HS256 verify with a local `AUTH_ACCEPT_LEGACY_COGNITO_JWT=true` cutover flag.

Three new tables. `UserModel` grows five columns. The two route handlers `/auth/login` and `/auth/register` lose their `APP_ENV=local` 503 guard; `/auth/register` is deleted entirely and replaced by `POST /api/v1/admin/users` (admin-only).

## Acceptance criteria

* [ ] AC-1: `cd backend && alembic upgrade head` runs cleanly. `alembic downgrade -1` followed by `upgrade head` is fully reversible. Verified by `python3 -m alembic upgrade head && python3 -m alembic downgrade -1 && python3 -m alembic upgrade head`.
* [ ] AC-2: `pytest tests/integration/test_auth_login.py tests/integration/test_auth_refresh.py tests/integration/test_auth_mfa.py tests/integration/test_auth_password_reset.py tests/integration/test_auth_admin.py tests/unit/test_totp.py tests/unit/test_lockout.py -v` is all green.
* [ ] AC-3: `pytest -q` full suite passes — the new prod-grade `/auth/login` does not regress any existing `APP_ENV=local` test that relies on the dev-token shape.
* [ ] AC-4: `ruff check .` clean.
* [ ] AC-5: `curl POST /api/v1/auth/login` returns identical JSON shape + similar response time for "wrong password", "no such user", and "locked user". Verified by hitting all three with `time curl`.
* [ ] AC-6: `curl POST /api/v1/auth/forgot-password` returns 204 for an existing user AND for an unknown email. Verified by hitting both.
* [ ] AC-7: A user with `mfa_enrolled_at != NULL` is denied login via `/auth/login` (returns `mfa_required: true` + `mfa_challenge_token`); login completes only via `/auth/mfa/verify-login` with a valid TOTP code. Verified by `tests/integration/test_auth_mfa.py::test_login_with_mfa_enrolled_requires_code`.
* [ ] AC-8: `DELETE /api/v1/auth/mfa` is admin-only — 403 for CLINICIAN, 204 for ADMIN. Verified by `tests/integration/test_auth_mfa.py::test_admin_clear_mfa_requires_admin`.
* [ ] AC-9: `POST /api/v1/admin/users` returns 403 for non-admin. Verified by `tests/integration/test_auth_admin.py::test_create_user_requires_admin`.
* [ ] AC-10: A successful password reset invalidates all existing refresh tokens for the user. Verified by `tests/integration/test_auth_password_reset.py::test_password_reset_revokes_refresh_tokens`.
* [ ] AC-11: Refresh-token rotation — using a refresh token returns a new refresh token; the old one is revoked. Verified by `tests/integration/test_auth_refresh.py::test_refresh_rotates_token`.
* [ ] AC-12: Audit event whitelist is updated for every new event type below; `AURION_AUDIT_STRICT=1` makes any kwarg leak break the build. Verified by `pytest tests/unit/test_audit_events.py`.

## DRY / SOLID check

* **Existing helpers reused**: `app.modules.auth.passwords` (bcrypt hash/verify), `app.core.kms_encryption.encrypt_str/decrypt_str` (for `mfa_secret_encrypted`), `app.core.clock.utcnow`, `app.core.uuids.to_uuid`, `app.modules.audit_log.get_audit_log_service`, `app.modules.auth.users_repository.create_user/get_by_email/get_user`, `require_role` (existing role-gate dep).
* **New helpers introduced**: `jwt_tokens`, `totp`, `password_reset`, `lockout`, `email` — five new submodules. Each is a single new responsibility (no third-copy concern: there is no existing JWT-minting / TOTP / lockout / reset code in the repo). One audit-emitter pattern reused throughout.
* **Single point of truth**: ONE `mint_access_token`, ONE `mint_refresh_token`, ONE `verify_access_token`. ONE TOTP module. ONE lockout module. `get_current_user` stays the single point that decides "who is this request?".

## Response shapes

### `POST /api/v1/auth/login` — success

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque-base64>",
  "token_type": "Bearer",
  "expires_in": 1800,
  "user": {
    "user_id": "<uuid>",
    "email": "perry@creoq.ca",
    "role": "CLINICIAN",
    "full_name": "Dr. Perry Gdalevitch",
    "mfa_enrolled": false
  }
}
```

### `POST /api/v1/auth/login` — MFA required

```json
{
  "mfa_required": true,
  "mfa_challenge_token": "<short-lived-jwt-5min>",
  "user_email": "perry@creoq.ca"
}
```

### `POST /api/v1/auth/mfa/verify-login` — success (same as login success)

### `POST /api/v1/auth/refresh` — success (rotates refresh; same shape as login success)

### `POST /api/v1/auth/logout` — 204

### `POST /api/v1/auth/forgot-password` — 204 (always; no account-existence signal)

### `POST /api/v1/auth/reset-password` — 204

### `GET /api/v1/auth/mfa/setup` — success

```json
{
  "secret": "<base32>",
  "provisioning_uri": "otpauth://totp/Aurion:perry@creoq.ca?secret=<base32>&issuer=Aurion"
}
```

### `POST /api/v1/auth/mfa/setup/verify` — 204

### `DELETE /api/v1/auth/mfa` — 204 (admin-only)

### `POST /api/v1/admin/users` — 201

```json
{
  "user_id": "<uuid>",
  "email": "new@aurionclinical.com",
  "full_name": "...",
  "role": "CLINICIAN",
  "temp_password": "<12-char>"
}
```

### `POST /api/v1/admin/users/{user_id}/reset-password` — 200

```json
{ "user_id": "<uuid>", "temp_password": "<12-char>" }
```

### Error shapes

`401 { "detail": "Invalid email or password." }` — same shape for wrong password, unknown user, locked user, MFA-required-but-no-code-yet (returned only after `/mfa/verify-login` with bad code). The MFA-required initial response is a 200 with `mfa_required: true` so the iOS client knows to prompt; this is not an attacker-observable distinction because the same response fires for any account that has MFA enrolled.

## Audit event whitelist (Q-03)

New `AuditEventType` members + their kwarg whitelists:

| Event | Whitelist |
|---|---|
| `LOGIN_SUCCESS` | `actor_id` |
| `LOGIN_FAILURE` | `target_user_id`, `reason` (one of `bad_password`, `unknown_user`, `inactive`) |
| `LOGIN_LOCKED` | `target_user_id`, `failed_count` |
| `LOGOUT` | `actor_id` |
| `MFA_ENROLLED` | `actor_id` |
| `MFA_RESET` | `actor_id`, `target_user_id` |
| `PASSWORD_RESET_REQUESTED` | `target_user_id` |
| `PASSWORD_CHANGED` | `actor_id`, `via` (one of `self_reset`, `admin_reset`) |
| `ADMIN_PASSWORD_RESET_ISSUED` | `actor_id`, `target_user_id` |
| `REFRESH_TOKEN_ISSUED` | `actor_id`, `token_id` |
| `REFRESH_TOKEN_ROTATED` | `actor_id`, `previous_token_id`, `new_token_id` |
| `REFRESH_TOKEN_REVOKED` | `actor_id`, `token_id`, `reason` |

NO email. NO password. NO TOTP secret. NO raw token. NO reset link. EVERY auth audit row goes to the synthetic session id `00000000-0000-0000-0000-000000000000` (same pattern as `VISION_CLIP_PROBED` and `PROMPT_USER_PROMPT_*`) because auth events are not session-scoped.

## Cutover runbook (CTO executes)

1. Deploy this PR to dev. Verify smoke (login, refresh, MFA setup, password reset link in log). Audit events appear in DynamoDB.
2. `AUTH_ACCEPT_LEGACY_COGNITO_JWT=true` env var in the dev ECS task — keeps Cognito tokens accepted in parallel during the transition.
3. Run `python3 backend/scripts/migrate_cognito_users_to_backend.py --dry-run` from a workstation with Cognito read perms. Confirm the user list.
4. Run the same script without `--dry-run`. Each new user's temp password prints next to their email. Operator distributes temp passwords out-of-band (Signal / phone).
5. Pilot users sign in once with temp password → forced password change via `POST /api/v1/auth/reset-password` (in a follow-up UI gate that comes with the iOS PR).
6. Pilot users enroll MFA via `GET /api/v1/auth/mfa/setup` → `POST /api/v1/auth/mfa/setup/verify`.
7. Once all users have logged in via the backend JWT path, flip `AUTH_ACCEPT_LEGACY_COGNITO_JWT=false`. Cognito tokens stop being accepted.
8. Run the Terraform cleanup PR — removes the Cognito user pool, IAM grants, and `COGNITO_*` env vars from ECS task definitions.

**Rollback**: flip `AUTH_ACCEPT_LEGACY_COGNITO_JWT=true` back and revert this PR. Users keep working on Cognito tokens. The new auth tables persist (data-only; no schema rollback required for safety).

## Out of scope

* iOS consumer rebase (separate PR after this lands).
* Web portal consumer rebase (separate PR).
* Terraform Cognito pool teardown (separate PR after all consumers are off Cognito).
* Forced password change on first login UI flow (depends on iOS rebase).
* Backup TOTP codes / recovery codes (deliberately not in v1; admin MFA-clear covers the lost-authenticator path).
* iOS-side TOTP UI testing (depends on iOS rebase).
* Replacing the dev-token shape (`<role>:<user_id>`) — deliberately preserved so the integration test suite doesn't need a sweeping rewrite.

## Test plan (executable)

1. `cd backend && python3 -m alembic upgrade head` → ok
2. `python3 -m alembic downgrade -1` → ok
3. `python3 -m alembic upgrade head` → ok
4. `python3 -m pytest tests/integration/test_auth_login.py tests/integration/test_auth_refresh.py tests/integration/test_auth_mfa.py tests/integration/test_auth_password_reset.py tests/integration/test_auth_admin.py tests/unit/test_totp.py tests/unit/test_lockout.py -v` → all green
5. `python3 -m pytest -q` → no regressions
6. `ruff check .` → clean
7. `docker compose up -d` → `curl -s localhost:8000/health` → 200
8. `curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' -d '{"email":"perry@creoq.ca","password":"perry"}'` → access + refresh tokens
9. `curl -s -X POST localhost:8000/api/v1/auth/refresh ...` → new access + rotated refresh
10. `curl -s -X POST localhost:8000/api/v1/auth/logout ...` → 204; subsequent refresh fails
11. `curl -s GET localhost:8000/api/v1/auth/mfa/setup -H "Authorization: Bearer <access>"` → secret + URI
12. `curl -s POST localhost:8000/api/v1/auth/mfa/setup/verify -H "Authorization: Bearer <access>" -d '{"code":"<pyotp>"}'` → 204
13. `curl -s POST localhost:8000/api/v1/auth/login ...` → `mfa_required: true`
14. `curl -s POST localhost:8000/api/v1/auth/forgot-password ...` → 204; check console for reset link
15. `curl -s POST localhost:8000/api/v1/auth/reset-password -d '{"token":"<from-log>","new_password":"..."}'` → 204

## Security implications

PHI: none. Email IS PHI when tied to a specific user — never goes into audit detail kwargs; only `actor_id` (UUID) and `target_user_id` (UUID) flow.

Secrets: `AUTH_JWT_SIGNING_KEY` and `AUTH_RESET_TOKEN_HMAC_KEY` live in Secrets Manager; the env vars are populated from there. Refresh tokens stored hashed (SHA-256) for fast revocation lookup. MFA secrets KMS-encrypted at rest. Refresh + reset tokens NEVER logged. Constant-time comparison: bcrypt for passwords; `hmac.compare_digest` for token-hash equality.

Audit: every auth state change written through the existing append-only DynamoDB path. Strict mode enforced in tests.

Consent gate / descriptive mode: not touched.
