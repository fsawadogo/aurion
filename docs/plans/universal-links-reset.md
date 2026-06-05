# AUTH-UNIVERSAL-LINKS — In-app password reset via Universal Links

## Goal

After PR #238 shipped the working email-link reset flow, the reset email points users at
`https://portal.aurionclinical.com/reset-password?token=…` which opens in Safari. CTO wants the
link to open **directly in the Aurion iOS app** so Marie and Perry never leave the app during a
reset — the web portal stays as the graceful fallback (no Aurion installed, AASA lookup failed).

## Flow

```
   Forgot password email
            │
            ▼
   Tap link in Mail.app
            │
            ▼
   iOS extracts URL → portal.aurionclinical.com/reset-password?token=…
            │
            ├── AASA file claims this path for com.aurionclinical.physician?
            │       ├── Yes → open Aurion app
            │       │           │
            │       │           ▼
            │       │   AurionApp.onContinueUserActivity(NSUserActivityTypeBrowsingWeb)
            │       │           │ validate host, path, ?token=
            │       │           ▼
            │       │   ResetLinkPayload.token = "<token>"
            │       │           │
            │       │           ▼
            │       │   ContentView.fullScreenCover → ResetPasswordView(token)
            │       │           │ enter new password + confirm
            │       │           ▼
            │       │   AurionAuth.resetPassword(token, newPassword)
            │       │           │ POST /api/v1/auth/reset-password
            │       │           ▼
            │       │   204 → success panel → tap "Sign in" → dismiss
            │       │   400 → "expired or already used" banner
            │       │
            │       └── No → Safari opens https://portal.aurionclinical.com/reset-password
            │               (the web portal page from PR #238 — unchanged)
```

## Inventory

### Web

- **`web/public/.well-known/apple-app-site-association`** (new, no extension):
  AASA file claims `/reset-password` with a non-empty `?token=` for App ID
  `2W2Z75Q5ZA.com.aurionclinical.physician`. v2 components format (iOS 13+).
  Includes a `webcredentials` block for iCloud Keychain auto-fill bonus.

### Infra

- **`infrastructure/amplify.tf`** — extend `custom_headers` YAML with a path-specific rule:
  ```yaml
  - pattern: '/.well-known/apple-app-site-association'
    headers:
      - key: 'Content-Type'
        value: 'application/json'
      - key: 'X-Content-Type-Options'
        value: 'nosniff'
  ```
  Apple's swcd daemon rejects the file unless served with `Content-Type: application/json`.
  Listed AFTER the catch-all so the merged headers win on Content-Type.

### iOS

- **`ios/Aurion/Aurion/Aurion.entitlements`** (new): claims
  `applinks:portal.aurionclinical.com` via `com.apple.developer.associated-domains`.
- **`ios/Aurion/Aurion.xcodeproj/project.pbxproj`**:
  add `CODE_SIGN_ENTITLEMENTS = Aurion/Aurion.entitlements;` to the App target's
  Debug + Release configurations. Widgets + test targets are NOT touched.
- **`ios/Aurion/Aurion/Network/AurionAuth.swift`** — `resetPassword(token, newPassword)` already
  exists from PR #235. No change needed.
- **`ios/Aurion/Aurion/App/ResetPasswordView.swift`** (new): in-app reset UI.
  Visual chrome mirrors `ForgotPasswordView`. Injects a `resetPassword` closure for tests.
  Inline validation (8+ chars, matches confirm). Maps `AuthError.invalidResetToken` to a
  localized banner.
- **`ios/Aurion/Aurion/App/AurionApp.swift`** — new
  `.onContinueUserActivity(NSUserActivityTypeBrowsingWeb)` handler validates host + path + token
  and writes to a shared `ResetLinkPayload` (`@StateObject` at app scope).
- **`ios/Aurion/Aurion/App/ContentView.swift`** — reads `ResetLinkPayload` via
  `@EnvironmentObject` and presents `ResetPasswordView` via `.fullScreenCover(item:)` with a
  small `Identifiable` wrapper (`ResetLinkToken`).
- **`ios/Aurion/Aurion/Resources/{en,fr}.lproj/Localizable.strings`** — 16 `login.resetPassword.*`
  keys at EN + FR parity.

### Tests

- **`ios/Aurion/AurionTests/UniversalLinksTests.swift`** — pure-function mirror of the deep-link
  extractor; happy path + every defensive rejection.
- **`ios/Aurion/AurionTests/ResetPasswordViewTests.swift`** — view contract.
- **`ios/Aurion/AurionTests/AurionAuthResetPasswordTests.swift`** — focused 204 / 400-with-detail
  / 400-with-malformed-body / transport-failure coverage.
- **`web/tests/AasaFile.spec.ts`** — JSON validity, App ID, `/reset-password` matcher with
  non-empty token, webcredentials presence, App ID shape.

## Apple Developer Portal — one CTO action

In `developer.apple.com → Identifiers → com.aurionclinical.physician → Capabilities`:

- Enable **Associated Domains** if not already enabled.

Enabling the capability may trigger a provisioning-profile regen. Xcode handles the regen
automatically on the next build via the Automatic signing path.

That's it. No portal-side rule to configure for AASA — Apple's swcd daemon fetches
`/.well-known/apple-app-site-association` directly from the claimed domain.

## DRY/SOLID gates

- ONE deep-link handler in `AurionApp.swift`.
- ONE `ResetLinkPayload` ObservableObject — minimal interface (`@Published var token: String?`).
- Password validation rule (8+ chars + confirm match) mirrors `web/lib/password-validation.ts`
  and the backend's Pydantic `Field(min_length=8, max_length=128)`.
- `AurionAuth` errors map through the existing `AuthError` enum. No parallel error type.
- AASA file: ONE source of truth at `web/public/.well-known/apple-app-site-association`.

## CLAUDE.md privacy gates

- Reset token NEVER logged from iOS (no `print(token)`, no `os_log`).
- Reset token NEVER persisted to Keychain — single-use, lives in view `@State` until consumed.
- URL handler validates host + path + presence of a non-empty `token` before any extraction.
- Backend error `detail` for the reset endpoint is account-enumeration-safe per PR #234's gate.

## Graceful degradation

- Aurion not installed → Safari handles the URL, web `/reset-password` page renders the same
  flow (PR #238 unchanged).
- AASA lookup failed (DNS, CDN cache, swcd timeout) → Safari handles it identically.
- Universal Links disabled in Settings → Safari handles it identically.
