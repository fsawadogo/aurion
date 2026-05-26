# Plan — WEB-COGNITO-UI web portal switches to Cognito hosted UI

## Task

`WEB-COGNITO-UI` — replace the web portal's `/auth/login` email-password
form with the same Cognito hosted UI + OAuth Authorization Code + PKCE
flow that iOS uses. The portal already shares the same Cognito user
pool (`ca-central-1_jWbQUgzbS`); the Cognito callback URLs for
`portal-dev.aurionclinical.com` were pre-wired in PR #1
(`infrastructure/cognito.tf`).

## Why

Two reasons:

1. **Security parity with iOS.** iOS users enroll TOTP MFA on first
   sign-in via the hosted UI. The web portal currently bypasses MFA
   via the dev `/auth/login` endpoint (clinical safety committee will
   flag this for pilot launch). The hosted UI inherits the user
   pool's `mfa_configuration = "ON"` so every web sign-in carries the
   same TOTP-enforced flow.
2. **One identity, one token.** Today a pilot user has a Cognito
   identity (for iOS) and a dev `/auth/login` session (for web). They
   diverge — when a user resets MFA, web stays valid. Switching web
   to Cognito means one canonical identity end-to-end.

## Approach

OAuth 2.0 Authorization Code flow with PKCE, mirroring
`ios/Aurion/Aurion/Network/CognitoAuth.swift`:

  1. User hits `/login` → page generates a PKCE code_verifier
     (random 64-byte hex) + code_challenge (SHA-256 of verifier,
     base64-url encoded) + state (random hex). Verifier + state go
     into `sessionStorage`.
  2. Page redirects to
     `https://aurion-dev.auth.ca-central-1.amazoncognito.com/oauth2/authorize`
     with `client_id`, `response_type=code`, `scope=openid email profile aws.cognito.signin.user.admin`,
     `redirect_uri=https://portal-dev.aurionclinical.com/api/auth/callback/cognito`,
     `code_challenge=<...>&code_challenge_method=S256`, `state=<...>`.
  3. Cognito hosts the sign-in form (with MFA prompt). On success,
     redirects to `/api/auth/callback/cognito?code=...&state=...`.
  4. Callback page validates state, POSTs to
     `…/oauth2/token` with `code` + `code_verifier`, gets
     `{access_token, id_token, refresh_token, expires_in}`.
  5. Tokens stored in `sessionStorage` (XSS surface is the admin-only
     portal on a controlled subdomain; httpOnly cookies would require
     a backend-set cookie which is out of scope for this PR).
  6. `fetchWithAuth` reads `id_token` from sessionStorage and sends
     `Authorization: Bearer <id_token>`. Backend `/auth/me` already
     validates this via Cognito JWKS — no backend changes needed.
  7. Refresh flow: if a request returns 401, exchange `refresh_token`
     for a fresh `id_token`; if that also fails, redirect to `/login`.

### Files

  - **New** `web/lib/cognito.ts` — PKCE helpers, `startSignIn`,
    `exchangeCodeForTokens`, `refreshTokens`, `signOut`,
    `getStoredIdToken`, `getStoredRefreshToken`. Single module for
    all Cognito interaction so the rest of the app can stay
    declarative.
  - **New** `web/app/auth/callback/cognito/page.tsx` — client-side
    page that runs `exchangeCodeForTokens` on mount and routes to
    `/dashboard`. The callback URL on Cognito's side
    (`/api/auth/callback/cognito`) is rewritten via Next.js to this
    page; we accept either.
  - **Replace** `web/app/(auth)/login/page.tsx` — drop the form,
    render a single "Sign in" button that calls `startSignIn()`.
  - **Modify** `web/lib/api.ts` — `fetchWithAuth` reads id_token
    from sessionStorage (falls back to the legacy `aurion_token`
    cookie for one release so we don't lock out in-flight sessions).
    On 401, try one silent refresh before redirecting.
  - **Modify** `web/components/Sidebar.tsx` — `logout()` now calls
    Cognito's `/logout` endpoint instead of just clearing the cookie.

### Env / config

  - `NEXT_PUBLIC_COGNITO_HOSTED_UI_BASE` —
    `https://aurion-dev.auth.ca-central-1.amazoncognito.com` (matches
    iOS `Config.swift.cognitoHostedUIBase`)
  - `NEXT_PUBLIC_COGNITO_CLIENT_ID` — `78kr08fp0q4gmgm5qpu65voq5j`
    (matches iOS)
  - `NEXT_PUBLIC_COGNITO_REDIRECT_URI` —
    `https://portal-dev.aurionclinical.com/api/auth/callback/cognito`
    (matches what's already in `cognito.tf` `callback_urls`)
  - `NEXT_PUBLIC_COGNITO_LOGOUT_URI` —
    `https://portal-dev.aurionclinical.com/auth/signed-out`

All four are baked at build time (Next.js public env vars). Amplify
build step injects them via `environment_variables` in `amplify.tf`
(needs a follow-up commit to add the three new keys; their values
mirror `infrastructure/cognito.tf`).

## Acceptance criteria

- [ ] AC-1: `cognito.ts` exports `startSignIn` which generates a PKCE
  verifier + challenge and assembles a valid Cognito `/oauth2/authorize`
  URL. Verified by Vitest case
  `web/lib/cognito.test.ts::startSignIn_builds_valid_authorize_url`
  asserting the URL contains `code_challenge_method=S256` and the
  challenge is a 43-char base64url string.
- [ ] AC-2: `exchangeCodeForTokens(code, verifier)` POSTs to
  `/oauth2/token` with `grant_type=authorization_code` + redirect_uri.
  Verified by a fetch-mock Vitest case asserting the request body
  shape.
- [ ] AC-3: `fetchWithAuth` reads `id_token` from `sessionStorage` and
  sends it as the Bearer token. Verified by Vitest against a stub
  `sessionStorage`.
- [ ] AC-4: On a 401 response, `fetchWithAuth` calls `refreshTokens`
  exactly once and retries the original request. Verified by
  fetch-mock + Vitest.
- [ ] AC-5: `signOut()` clears stored tokens and redirects to Cognito's
  `/logout` endpoint with `client_id` + `logout_uri`. Verified by
  Vitest asserting `window.location.href` ends in the expected URL.
- [ ] AC-6: Manual end-to-end once deployed — sign in via Cognito
  hosted UI, complete TOTP enrollment, land on `/dashboard`,
  refresh the page (token survives), sign out, redirected to the
  hosted UI logout page.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - iOS `CognitoAuth.swift` is the reference; the JS port mirrors
    its `signIn`, `exchangeCode`, `refreshIfNeeded` shapes so future
    eyes have one mental model.
  - `infrastructure/cognito.tf` callback URLs already include the
    portal — no infra change in this PR (separate amplify.tf env
    var update can land alongside).
  - `fetchWithAuth` stays the single auth-mediation point on the
    web side.
- **New helper introduced?**: `web/lib/cognito.ts` is new but
  justified — Cognito interaction was previously not a concern of
  the web bundle. Single module, single responsibility (auth).
- **iOS UI tasks only — `mobile-ios-design` consulted**: N/A — web only.

## Out of scope

- httpOnly cookie token storage (requires a Next.js middleware /
  route handler to set the cookie server-side; sessionStorage is
  pragmatic for the admin portal)
- Sign-in-with-Apple, social providers
- Per-session token rotation logging
- Adding the 4 new `NEXT_PUBLIC_*` env vars to `amplify.tf` (it's a
  3-line Terraform edit; doing it in this PR couples backend infra
  with frontend behavior — splitting keeps the diff focused)
- Removing the dev `/auth/login` endpoint — leave it disabled in
  prod via the existing env-gate; deletion is a separate
  cleanup task

## Test plan (executable)

1. `cd web && npx vitest run lib/cognito.test.ts` (expect AC-1..5
   green; Vitest may need a new dev-dependency — if so, the PR adds
   `vitest` to `web/package.json` devDependencies)
2. `cd web && npx tsc --noEmit` (expect 0 errors)
3. `cd web && npx next lint` (expect 0 errors)
4. CI `build` + `lint` + `test` jobs green

## Security implications

- **PKCE is mandatory** — Cognito's hosted UI flow accepts both
  S256 (used here) and `plain` (rejected). No code path falls back to
  `plain`.
- **State parameter validated** on callback — defends against CSRF
  on the redirect URI.
- **id_token in sessionStorage**: XSS-bound. The admin portal serves
  only typed React; no inline HTML injection paths and no third-party
  inline scripts. Risk is bounded; we trade against the alternative
  (httpOnly cookies + a Next.js middleware which is heavier).
- **Refresh token lifetime**: 30 days (matches Cognito user pool
  client config). On expiry, user re-signs through hosted UI.
- **Backend `/auth/me` is the validator** — it checks the JWT
  signature via JWKS, the issuer (`iss`), the audience (`aud`),
  expiration (`exp`), and pulls the role from the Cognito group
  claim. No additional validation in the frontend.
- **No PHI in logs**: the auth flow carries email + sub only; no
  patient data crosses this boundary.
- **MFA enforced**: Cognito pool's `mfa_configuration = "ON"` means
  every sign-in (including web) goes through TOTP, matching the
  iOS path.
