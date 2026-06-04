# AUR-COG-MFA-IOS — TOTP MFA support in native Cognito sign-in

## Task

Add SOFTWARE_TOKEN_MFA + MFA_SETUP challenge handling to the iOS native
Cognito client (`CognitoNativeAuth`) and present two new SwiftUI screens —
daily-login 6-digit entry and first-time TOTP enrolment — so the dev pool
can flip `mfa_configuration` back to `ON` without the app erroring out.

## Why

Dev pool MFA is currently `OFF` (`infrastructure/cognito.tf` line 46,
tracked as `AUR-COG-MFA-RESTORE`) because the native sign-in client we
shipped in PR #31 detects `SOFTWARE_TOKEN_MFA` and only surfaces an
"unsupported" error — no UI to handle the challenge.

Pilot launch requires MFA back on. This iOS PR ships first; a follow-up
Terraform PR flips `mfa_configuration = "ON"` and Marie/Perry enrol on
their next sign-in.

CLAUDE.md §"Non-Negotiable Technical Rules" — secrets via Cognito (the
TOTP shared secret lives in the user pool, never in our backend). No PHI
in error messages. No backend round-trip with the user's TOTP code; the
verification roundtrip is iOS ↔ Cognito only.

## Approach

### Cognito challenge flow

```
Daily login (already enrolled):
  InitiateAuth                                            ─→ {ChallengeName: SOFTWARE_TOKEN_MFA, Session}
  RespondToAuthChallenge(SOFTWARE_TOKEN_MFA, code, Session)─→ {AuthenticationResult}

First sign-in after MFA = ON (no TOTP yet):
  InitiateAuth                                            ─→ {ChallengeName: MFA_SETUP, Session_A}
  AssociateSoftwareToken(Session_A)                       ─→ {SecretCode, Session_B}
  [user scans QR / enters code into authenticator app]
  VerifySoftwareToken(Session_B, code, FriendlyDeviceName)─→ {Status: SUCCESS, Session_C}
  RespondToAuthChallenge(MFA_SETUP, Session_C, USERNAME)  ─→ {AuthenticationResult}

Post-signin opt-in (already authenticated, AccessToken in hand):
  AssociateSoftwareToken(AccessToken)                     ─→ {SecretCode}
  VerifySoftwareToken(AccessToken, code, FriendlyDeviceName)─→ {Status: SUCCESS}
```

The MFA_SETUP branch above is what this PR implements end-to-end. The
post-signin opt-in path is NOT in scope for this PR — it would let an
existing physician self-enrol from Profile › Security, but we're letting
the admin-created accounts hit MFA_SETUP on first login instead.

### File changes

| Layer | File | Change |
|-------|------|--------|
| Network | `ios/Aurion/Aurion/Network/CognitoNativeAuth.swift` | +3 public methods, +1 SignInOutcome case, +new types |
| UI | `ios/Aurion/Aurion/App/MfaChallengeView.swift` | NEW — daily 6-digit entry |
| UI | `ios/Aurion/Aurion/App/MfaSetupView.swift` | NEW — QR + secret + verify |
| UI | `ios/Aurion/Aurion/App/TotpCodeField.swift` | NEW — shared 6-cell input (DRY) |
| Wire | `ios/Aurion/Aurion/App/ContentView.swift` | Replace error case with screen presentation |
| Strings | `ios/Aurion/Aurion/Resources/{en,fr}.lproj/Localizable.strings` | New keys, remove `login.mfaUnsupported` |
| Tests | `ios/Aurion/AurionTests/CognitoNativeAuthMfaTests.swift` | NEW |
| Tests | `ios/Aurion/AurionTests/MfaChallengeViewTests.swift` | NEW |

## Acceptance criteria

- [ ] `CognitoNativeAuth.respondToTotpChallenge` posts to
      `RespondToAuthChallenge` with `ChallengeName: "SOFTWARE_TOKEN_MFA"`
      and returns `.authenticated` on success.
- [ ] `CognitoNativeAuth.signInForMfaSetup` posts to
      `RespondToAuthChallenge` with `ChallengeName: "MFA_SETUP"` and
      returns a new Session for AssociateSoftwareToken.
- [ ] `CognitoNativeAuth.beginTotpSetup` parses `SecretCode` + (optional)
      `Session` from either AccessToken or Session-based call.
- [ ] `CognitoNativeAuth.verifyTotpSetup` maps `{Status: SUCCESS}` →
      `.success`, `{Status: ERROR}` → `.codeMismatch`,
      `CodeMismatchException` → `.codeMismatch`,
      `ExpiredCodeException` → bubbled error.
- [ ] `SignInOutcome.mfaSetupRequired(session, username)` dispatched when
      Cognito returns `ChallengeName == "MFA_SETUP"`.
- [ ] `MfaChallengeView` presents on `.fullScreenCover` from
      `.mfaRequired`; six-digit entry → verify → `.authenticated`.
- [ ] `MfaSetupView` presents on `.fullScreenCover` from
      `.mfaSetupRequired`; renders QR (`otpauth://totp/Aurion:<email>?secret=…&issuer=Aurion`)
      + copyable secret; six-digit confirm → `.success` → `.authenticated`.
- [ ] EN + FR strings at parity. `login.mfaUnsupported` removed from both.
- [ ] `login.mfa.challenge.invalidCode` shown on `.codeMismatch` without
      echoing the user-entered code (CLAUDE.md no-PHI rule extended to
      auth secrets).
- [ ] xcodebuild build + AurionTests target green.
- [ ] Visual smoke: existing sign-in still works (no MFA branch hit yet).

## DRY / SOLID check

- **DRY**: `TotpCodeField` is the single 6-digit input component, used by
  both challenge and setup confirm phases. `CognitoNativeAuth` is the sole
  network surface; no view talks to URLSession. `NativeAuthError` is the
  sole error mapping site. One regex/length validator for the 6-digit code.
- **SRP**: `CognitoNativeAuth` is auth I/O; views are presentation;
  `ContentView` is state-machine orchestration. No mixing.
- **OCP**: New SignInOutcome cases extend the enum; existing branches in
  callers continue to work via Swift's exhaustive-switch warning.
- **LSP**: New methods follow the same `async throws -> SignInOutcome`
  shape as `signIn` / `completeNewPassword` — interchangeable at the
  caller boundary.
- **ISP**: `TotpCodeField` exposes a minimal `Binding<String>` + onComplete
  closure. No carrier API for unrelated state.
- **DIP**: View ↔ network goes through `CognitoNativeAuth.shared`; tests
  inject via URLProtocol mock, not by stubbing the view.

## Out of scope

- Terraform flip of `mfa_configuration` to `ON` — follow-up PR.
- Post-signin MFA opt-in flow (Profile › Security › Enable 2FA).
- SMS MFA fallback (deliberately omitted per `cognito.tf` line 43).
- Per-user TOTP secret rotation / multi-device enrolment.
- Recovery codes (Cognito doesn't expose them via TOTP — handled via
  admin password reset).

## Test plan (executable)

```bash
# Build
cd ios/Aurion && xcodebuild build \
  -scheme Aurion \
  -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5'

# Target tests
xcodebuild test \
  -scheme Aurion \
  -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' \
  -only-testing:AurionTests/CognitoNativeAuthMfaTests \
  -only-testing:AurionTests/MfaChallengeViewTests

# Full suite — no regression
xcodebuild test \
  -scheme Aurion \
  -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' \
  -only-testing:AurionTests
```

Manual smoke (post-merge, with a temp MFA-enabled test account):

```bash
# Enable MFA on a single test user (no global flip)
aws cognito-idp admin-set-user-mfa-preference \
  --user-pool-id <DEV_POOL_ID> \
  --username mfa-test@aurionclinical.com \
  --software-token-mfa-settings Enabled=true,PreferredMfa=true \
  --region ca-central-1

# Sign in → MFA_SETUP challenge → scan QR → enter 6-digit code → in.
```

## Security implications

- TOTP shared secret displayed in-memory only during `MfaSetupView`
  lifetime. Never persisted to Keychain (Cognito holds the canonical
  association). Never logged.
- `friendlyDeviceName` uses `UIDevice.current.name` if non-empty, else
  literal `"Aurion iPhone"` — non-PII identifier so the user pool's
  registered-device list is readable.
- 6-digit code never echoed in error messages or analytics. Mismatch
  surfaces a generic "Incorrect code" string.
- No backend round-trip with the code; iOS → Cognito only. The backend's
  `/me` lookup that follows happens AFTER `.authenticated` on the same
  AccessToken the password-only flow uses today.

## Follow-up (separate PRs)

1. Terraform: flip `mfa_configuration = "ON"` in `infrastructure/cognito.tf`,
   uncomment the `software_token_mfa_configuration` block. Close
   `AUR-COG-MFA-RESTORE`.
2. Optional: Profile › Security › "Enable 2FA" entry for users who want
   to opt in before being forced.
