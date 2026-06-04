# AUTH-PIVOT-IOS — iOS rebase off Cognito onto backend JWT

## Task

`AUTH-PIVOT-IOS` — drop Cognito from the iOS app. Rebase the SwiftUI
auth flow onto the new backend JWT + TOTP + email-link password reset
endpoints shipped in PR #234 (AUTH-PIVOT-BACKEND).

## Why

PR #233 (`lane-ios/cognito-totp-mfa`) shipped the SwiftUI for native
Cognito TOTP, then was closed as superseded when the CTO decided to
drop Cognito entirely. PR #234 took ownership of every auth state
change on the backend: login, refresh, logout, MFA setup + verify,
forgot/reset password. This PR is the iOS consumer rebase — same UI
surface (cherry-picked from #233), entirely new network layer.

Cutover compatibility is mechanical:
1. Backend ships with `AUTH_ACCEPT_LEGACY_COGNITO_JWT=true` so the
   Cognito tokens currently in physicians' Keychains continue to work
   on `/api/v1/*` calls.
2. This PR ships. The Cognito client is gone — any new sign-in goes
   through backend JWTs.
3. The CTO runs `backend/scripts/migrate_cognito_users_to_backend.py`
   to seed the backend users table with temp passwords for each pilot
   physician.
4. Physicians sign in once with the temp password (out-of-band), enroll
   MFA via the QR screen, get their canonical backend tokens.
5. `AUTH_ACCEPT_LEGACY_COGNITO_JWT=false` flips. Cognito tokens stop
   being accepted. Cognito Terraform tears down in a follow-up PR.

## Approach

### What got cherry-picked from #233

* `ios/Aurion/Aurion/App/TotpCodeField.swift` — UI primitive (6-cell
  TOTP code entry, sanitize/isComplete helpers, premium UI tokens).
  Unchanged.
* `ios/Aurion/Aurion/App/MfaChallengeView.swift` — daily TOTP gate.
  Rewired onto `AurionAuth.verifyLoginMfa`.
* `ios/Aurion/Aurion/App/MfaSetupView.swift` — first-time enrollment
  with QR + base32 manual fallback. Rewired onto
  `AurionAuth.beginMfaSetup` + `AurionAuth.verifyMfaSetup`. Cognito's
  three-hop dance (`signInForMfaSetup` → `beginTotpSetup` →
  `verifyTotpSetup` → `signInForMfaSetup` again) collapses to a
  two-call shape against the backend, which is structurally simpler.
* EN + FR strings under `login.mfa.challenge.*` and `login.mfa.setup.*`.

### What's net-new

* `ios/Aurion/Aurion/Network/AurionAuth.swift` — the sole iOS auth
  client. Eight public methods covering the eight backend endpoints
  plus a `refreshIfNeeded` convenience wrapper that mirrors the
  contract the deleted `CognitoAuth.refreshIfNeeded` had.
* `ios/Aurion/Aurion/App/ForgotPasswordView.swift` — single email field
  + confirmation panel matching the backend's always-204 contract.
  Same confirmation regardless of email validity.
* "Forgot password?" link below the password field on `LoginView`.

### What got deleted

* `ios/Aurion/Aurion/Network/CognitoAuth.swift` — hosted-UI path.
* `ios/Aurion/Aurion/Network/CognitoNativeAuth.swift` — native
  USER_PASSWORD_AUTH client.
* The four `cognito*` constants and one set of OAuth scopes from
  `ios/Aurion/Aurion/App/Config.swift`.
* The `newPasswordRequired` branch from `LoginView.handleOutcome` —
  backend has no first-sign-in ceremony; admin temp passwords behave
  like any other password.

## Surface — `AurionAuth`

```swift
@MainActor
final class AurionAuth {
    static let shared: AurionAuth
    init(urlSession: URLSession = .shared)  // injectable for tests

    enum SignInOutcome {
        case authenticated(AuthSession)
        case mfaRequired(challengeToken: String, userEmail: String)
    }
    enum MfaSetupOutcome { case success, codeMismatch }

    func signIn(email: String, password: String) async throws -> SignInOutcome
    func verifyLoginMfa(challengeToken: String, code: String) async throws -> AuthSession
    func refresh(refreshToken: String) async throws -> AuthSession
    func refreshIfNeeded() async throws -> AuthSession?
    func logout(refreshToken: String) async
    func signOut()
    func requestPasswordReset(email: String) async throws
    func resetPassword(token: String, newPassword: String) async throws
    func beginMfaSetup() async throws -> (secret: String, provisioningURI: String)
    func verifyMfaSetup(code: String) async throws -> MfaSetupOutcome
}
```

All wire shapes mirror `docs/plans/auth-pivot-backend-jwt.md`:

| Method | Endpoint | Request body | Response |
|---|---|---|---|
| signIn | `POST /api/v1/auth/login` | `{email, password}` | `{access_token, refresh_token, expires_in, user}` OR `{mfa_required: true, mfa_challenge_token, user_email}` |
| verifyLoginMfa | `POST /api/v1/auth/mfa/verify-login` | `{mfa_challenge_token, code}` | success shape |
| refresh | `POST /api/v1/auth/refresh` | `{refresh_token}` | success shape |
| logout | `POST /api/v1/auth/logout` | `{refresh_token}` | 204 |
| requestPasswordReset | `POST /api/v1/auth/forgot-password` | `{email}` | 204 (always) |
| resetPassword | `POST /api/v1/auth/reset-password` | `{token, new_password}` | 204 |
| beginMfaSetup | `GET /api/v1/auth/mfa/setup` | — | `{secret, provisioning_uri}` |
| verifyMfaSetup | `POST /api/v1/auth/mfa/setup/verify` | `{code}` | 204 |

## DRY / SOLID check

* **DRY**: ONE auth client (`AurionAuth`). ONE TOTP code primitive
  (`TotpCodeField`, cherry-picked unchanged). ONE token storage path
  (`KeychainHelper.saveTokens` — signature preserved, semantics
  unchanged). ONE login state machine (`ContentView.handleOutcome`,
  extended in place not forked).
* **SRP**: `AurionAuth` does network only; `MfaSetupView` /
  `MfaChallengeView` / `ForgotPasswordView` do presentation only;
  Keychain decisions stay in `KeychainHelper`.
* **OCP**: New error categories extend `AuthError`. The
  challenge-token shape mirrors the legacy `mfaRequired` payload so
  the `handleOutcome` switch grew narrower, not branchier.
* **LSP**: `AuthSession` shape is byte-identical to the deleted
  Cognito version (access / id / refresh / expiresAt) — the
  ContentView code that read `session.refreshToken` keeps working
  unchanged.
* **ISP**: `AurionAuth` exposes only the methods the UI actually
  needs. No "kitchen sink" entry point.
* **DIP**: `URLSession` is injected via the initializer so tests can
  plug `URLProtocol`-based fakes.

## Security gates (CLAUDE.md)

* Login error message identical for wrong-password / unknown-user /
  locked — backend already returns the same shape; client maps every
  4xx login response to `AuthError.invalidCredentials` →
  "Invalid email or password."
* TOTP secret displayed in `MfaSetupView.@State`, never persisted,
  never logged, never sent back. The backend already has its own
  KMS-encrypted copy.
* Password / refresh / reset tokens never reach Logger / NSLog / OSLog.
  `AurionAuth` doesn't log request bodies; error mapping at the
  response layer doesn't include the raw body.
* Network error messages don't echo the entered code.

## Verification gate (§8)

1. `xcodebuild build -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5'` → BUILD SUCCEEDED
2. `xcodebuild test ... -only-testing:AurionTests/AurionAuthTests` → all pass
3. `xcodebuild test ... -only-testing:AurionTests/MfaChallengeViewTests` → all pass
4. `xcodebuild test ... -only-testing:AurionTests/ForgotPasswordViewTests` → all pass
5. `xcodebuild test ... -only-testing:AurionTests` → no regressions
6. `grep -rn "Cognito" ios/Aurion/Aurion --include="*.swift"` → empty (excluding comments referencing the deletion)
7. Manual smoke (optional, requires dev backend reachable):
   ```bash
   xcodebuild build -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' \
     | grep -E "(BUILD SUCCEEDED|error:)"
   # Then in the simulator:
   # - Sign in with perry@creoq.ca / perry
   # - Expect tokens in Keychain, /me lookup succeeds
   # - Tap "Forgot password?" → submit → "check your inbox" panel
   # - In Profile > Security (post-pilot UI), tap "Enroll MFA" → scan QR
   #   → enter code → MFA enrolled
   # - Sign out, sign back in → MFA challenge → enter code → in
   ```

## Out of scope

* Forced password-reset-on-first-login UI (admin temp passwords work
  like any password; rotation prompt is a follow-up).
* Reset-via-app-deep-link (reset link opens the web portal, not the
  app — per task spec).
* Backend Cognito Terraform teardown (separate PR after all consumers
  are off Cognito).
* Backend test suite changes (the backend's tests live in PR #234).
* Web portal rebase (separate PR).
* Profile > Security → "Set up MFA" entry point. The MFA screens are
  wired into the login state machine for now; surfacing them as a
  one-time post-onboarding gate or a Profile setting comes in a
  follow-up.
* `RegisterView` removal. The backend killed `/auth/register`, so the
  on-screen toggle would 404 — we drop the route from the `AuthView`
  switch but leave the SwiftUI file alone for a future clean-up PR.

## Test plan (executable)

1. `cd ios/Aurion && xcodebuild build -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' -quiet 2>&1 | tail -5` → `** BUILD SUCCEEDED **`
2. `xcodebuild test -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' -only-testing:AurionTests/AurionAuthTests -only-testing:AurionTests/MfaChallengeViewTests -only-testing:AurionTests/ForgotPasswordViewTests -quiet 2>&1 | tail -10` → all green
3. `xcodebuild test -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' -only-testing:AurionTests -quiet 2>&1 | tail -10` → no regressions
4. `grep -rn "CognitoAuth\|CognitoNativeAuth\|cognitoClientID\|cognitoRegion\|cognitoHostedUIBase" ios/Aurion/Aurion --include="*.swift" | grep -v "// "` → empty

## Security implications

* Auth secrets stay off the wire and out of the audit log
  (backend-side). The iOS client passes credentials in one direction,
  through HTTPS, with no caching layer in between.
* MFA secret rendered in `MfaSetupView` but never persisted or
  re-transmitted — Cognito's "secret travels with the user" guarantee
  is preserved.
* Refresh tokens go to Keychain; biometric "remember me" credential
  storage is unchanged (`KeychainHelper.saveBiometricCredential`
  signature preserved).
