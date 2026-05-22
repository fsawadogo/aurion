# Aurion — fastlane

CLI automation for Apple Developer Portal + App Store Connect. Uses
the **App Store Connect API key** (the same one CI uses for TestFlight
uploads) — no 2FA prompts, no session cookies.

## One-time setup

### 1. Install fastlane

```bash
brew install fastlane
fastlane --version   # expect 2.220+ for App Store Connect API key support
```

### 2. Generate the App Store Connect API key (web UI, bootstrap-only)

Same key serves both CI and these local lanes. If you already created
it for `.github/workflows/ios-testflight.yml`, **reuse it** — don't
generate two.

1. **App Store Connect → Users and Access → Integrations → Keys → Generate API Key**
2. Name: `Aurion CI`. Role: **Admin**.
3. Download the `.p8`. Note the **Key ID** (10 chars) + **Issuer ID** (UUID).

### 3. Set environment variables

Add to `~/.zshrc`:

```bash
# Apple Developer
export APPLE_DEV_EMAIL="faical.sawadogo@aurionclinical.com"
export APPLE_TEAM_ID="ABCDEFGHIJ"   # 10-char Team ID from developer.apple.com → Membership

# App Store Connect API (reused from CI)
export APP_STORE_CONNECT_KEY_ID="ABC1234567"
export APP_STORE_CONNECT_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export APP_STORE_CONNECT_KEY_P8="$(base64 -i ~/Downloads/AuthKey_ABC1234567.p8)"

# Pilot tester emails — used by `fastlane invite_pilot_physicians`
export PILOT_TESTER_EMAILS="perry@creoq.ca,marie@creoq.ca"
```

Reload: `exec zsh`.

## Lanes

All lanes run from `ios/Aurion/`:

```bash
cd ios/Aurion
```

### `fastlane bootstrap`

**Run once.** Creates both App IDs (`com.aurionclinical.aurion` + the
`AurionWidgets` extension bundle id) in the developer portal AND the
App Store Connect app record. Idempotent — re-running with existing
IDs is a no-op.

```bash
fastlane bootstrap
```

Expected output ends with:

```
[16:42:13]: ✅ App Store Connect record for 'Aurion' is ready.
```

### `fastlane upload_testflight`

Local build + TestFlight upload. Mirrors the CI workflow — useful for
the very first build, or as a one-off if CI is wedged.

```bash
fastlane upload_testflight
```

### `fastlane invite_pilot_physicians`

Invites the emails in `$PILOT_TESTER_EMAILS` as internal testers.

```bash
fastlane invite_pilot_physicians
```

### `fastlane list_testers`

Sanity check — prints currently-invited testers.

```bash
fastlane list_testers
```

## What's intentionally NOT here

- **`fastlane match`** (cert/profile sync). The
  `xcodebuild -allowProvisioningUpdates` flag in CI uses the API key
  to fetch/refresh certs on demand — simpler than match for a single-
  developer team. Add match when a second developer needs the same
  signing identity.
- **App Store submission** (`upload_to_app_store`). Pilot uses
  TestFlight internal testing only. When you submit to App Store
  proper, add a `release` lane.
- **Screenshots automation**. App Store listing isn't needed for
  TestFlight pilot.

## Troubleshooting

- **`Could not find action 'app_store_connect_api_key'`** — your
  fastlane is older than 2.196.0. Update: `brew upgrade fastlane`.
- **`No team selected, multiple teams found`** — `APPLE_TEAM_ID` env
  var isn't set. Get it from developer.apple.com → top-right account
  menu → Membership → Team ID.
- **`Invalid API key`** — the `.p8` decoding is wrong. Re-run the
  `base64 -i` command in step 3; make sure no newlines got into the
  middle of the value.
