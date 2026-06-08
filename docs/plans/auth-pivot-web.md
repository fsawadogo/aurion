# Auth pivot — Web portal (Cognito → backend bcrypt-JWT)

**Status:** implemented 2026-06-08 · branch `lane-web/auth-pivot-jwt`
**Closes the gap:** the backend (`auth-pivot-backend-jwt.md`, PR #234) and iOS
(`auth-pivot-ios.md`, PR #235) moved off AWS Cognito to the backend's own
bcrypt + JWT auth on 2026-06-04/05. The **web portal was never migrated** — it
remained the lone platform on Cognito.

## The bug this fixes

The deployed portal authenticated cloud logins by POSTing **directly to
Cognito** (`cognito-idp.ca-central-1.amazonaws.com`, `InitiateAuth` /
`USER_PASSWORD_AUTH`, app client `78kr08fp0q4gmgm5qpu65voq5j`) and only used the
backend `/api/v1/auth/login` route when `NEXT_PUBLIC_API_URL` was localhost.

Two consequences:
1. Accounts created in the backend DB (the post-pivot source of truth) **do not
   exist in the Cognito pool**, so login returned `400 NotAuthorizedException`
   (masked by `PreventUserExistenceErrors=ENABLED`).
2. Even a successful Cognito sign-in could not complete: the portal then calls
   the backend `/api/v1/auth/me` with the Cognito id_token, but the deployed
   backend has `AUTH_ACCEPT_LEGACY_COGNITO_JWT` unset (= false), so it rejects
   Cognito tokens. The portal was effectively unusable in the cloud.

## The change

Single auth path against the backend bcrypt-JWT API — same system as iOS.

- `web/app/(auth)/login/page.tsx` — removed the `IS_LOCAL` Cognito/JWT split;
  always calls `login()`. Handles the `mfa_required` response with a TOTP code
  step (`/api/v1/auth/mfa/verify-login`). Routes by `user.role`. `IS_LOCAL` now
  only gates the optional "local dev credentials" hint panel.
- `web/lib/api.ts` — `getToken()` reads the `aurion_token` cookie only (no
  Cognito id_token preference). Added access+refresh cookie storage,
  `refreshAccessToken()` against `/api/v1/auth/refresh` (rotating), MFA-verify,
  and a `logout()` that revokes the refresh token via `/api/v1/auth/logout`.
  `fetchWithAuth` does silent-refresh-on-401 then bounces to /login.
- `web/types/index.ts` — `AuthResponse` corrected to mirror the backend
  `LoginSuccessResponse` (`{access_token, refresh_token, expires_in, user{…}}`);
  added `AuthUser`, `MfaRequiredResponse`, `LoginResult`. (The old flat type
  never matched the backend — the localhost path was half-broken too.)
- Deleted dead Cognito code: `web/lib/cognito.ts`, the orphaned
  `web/app/api/auth/callback/cognito/page.tsx`, and `web/app/auth/signed-out`.

## Token storage trade-off

Access + refresh tokens live in non-httpOnly cookies (`aurion_token`,
`aurion_refresh`) so client JS can attach the bearer header and run
silent-refresh. This matches the portal's pre-existing `aurion_token` approach
and is an accepted MVP trade-off for an internal admin portal. **Post-MVP
hardening:** httpOnly cookies + a server-side refresh proxy.

## Operational follow-ups

- The Cognito user pool `ca-central-1_jWbQUgzbS` is now unused by the app. Leave
  it provisioned (dormant) for MVP; decommission post-MVP. Re-adding Cognito SSO
  is a post-MVP item.
- `AUR-COG-MFA-RESTORE`: restoring Cognito pool MFA no longer affects the portal
  (it no longer talks to Cognito) — but reconcile the note so the dormant pool
  isn't assumed to gate web access.
- Portal users must exist in the **backend DB** (not Cognito). The pilot iOS
  users already do (iOS is on backend JWT). `admin@aurionclinical.com` was
  created in the backend DB on 2026-06-08.
