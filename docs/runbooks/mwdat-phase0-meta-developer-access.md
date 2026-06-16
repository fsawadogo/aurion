# MWDAT Phase 0 — Meta Wearables Developer Access (Ray-Ban Meta glasses)

**Goal:** unblock the Meta Wearables Device Access Toolkit (MWDAT) glasses integration by
registering Aurion on Meta's **Wearables Developer Center**, obtaining the `MetaAppID` +
`ClientToken`, and confirming the distribution path. This is the **external gate** — Phase 3
(the real `MetaWearablesSource` implementation) cannot be validated or shipped without it.

> Phases **1** (SDK link + app config, #442) and **2** (`VideoClipSource` clip-seam refactor,
> #440) are already on `main`. Full plan: `~/.claude/plans/zazzy-dreaming-galaxy.md`.
> Developer preview docs: <https://wearables.developer.meta.com/docs/develop/dat/build-integration-ios/>

---

## Who does what

These steps are **human-only** — they require a Meta developer login and accepting Meta's
**Developer Terms** (a legal agreement). They cannot be automated by CI or an agent. Owner:
**Faïçal (CTO)** or a delegate with authority to bind Aurion to Meta's terms.

Everything the engineer side needs is pre-filled below; once the two credentials come back,
wiring them in is copy-paste (see "Where the values go").

---

## Pre-filled Aurion inputs (Meta's portal will ask for these)

| Field | Value | Source |
|---|---|---|
| Apple **Team ID** | `2W2Z75Q5ZA` | `Aurion.xcodeproj` `DEVELOPMENT_TEAM` |
| App **Bundle ID** | `com.aurionclinical.physician` | `PRODUCT_BUNDLE_IDENTIFIER` (main app target) |
| **App-link URL scheme** | `aurion://` | existing `CFBundleURLSchemes` in `ios/Aurion/Aurion-Info.plist` (reuse it; the OAuth scheme `aurion` is already registered) |
| **MFi / ExternalAccessory protocol** | `com.meta.ar.wearable` | fixed by Meta SDK |
| App display name | Aurion | — |

## Steps (Wearables Developer Center)

1. Go to <https://developer.meta.com/wearables> → **create an account** / sign in with the Meta
   developer identity that should own this integration.
2. **Register the organization** (Aurion Clinical AI) and **accept the Developer Terms**.
3. Request **developer-preview / partner access** for the bundle id `com.aurionclinical.physician`.
4. In **Manage Projects**, create a project/app for Aurion. Meta **autogenerates** the
   **`MetaAppID` (APPLICATION_ID)** and **`ClientToken` (CLIENT_TOKEN)** — copy both.
5. Confirm the app-link callback scheme you registered matches the app (`aurion://`), and that the
   MFi protocol string is `com.meta.ar.wearable`.
6. Create a **release channel** and confirm test users can be added (this is how MWDAT builds reach
   testers — see distribution below).
7. **Hand off the two secrets** (`MetaAppID`, `ClientToken`) via the secret channel — NOT in
   Slack/email/commit. They are client identifiers but follow the secrets-never-in-git rule.

## Confirm the distribution path (decision needed)

- **App Store publish is NOT supported** for MWDAT builds (the ExternalAccessory framework + MFi /
  privacy-manifest triggers App Store rejection; Meta targets broad publish "in the future").
- → the glasses build distributes to **internal TestFlight** testers (internal testers bypass Beta
  App Review; external groups likely get rejected for the ExternalAccessory build).
- **Deviation flagged:** pilot physicians probably need to be **internal** TestFlight testers for the
  glasses build — this overrides the usual "distribute to both internal AND external groups" rule for
  *this build only*. Confirm Perry/Marie (and the MWDAT testers) are on the internal group.

---

## Where the values go (engineer side, once credentials arrive)

The plumbing intentionally leaves the SDK **inert** until these are set (`Wearables.configure()`
throws and is ignored → "dark" state). To activate:

1. **GitHub Actions secrets** (repo settings → Secrets → Actions), mirroring the App Store Connect
   keys in `.github/workflows/ios-testflight.yml`:
   - `MWDAT_META_APP_ID`
   - `MWDAT_CLIENT_TOKEN`
   Then inject them into the `xcodebuild` step as build settings
   (`MWDAT_META_APP_ID=… MWDAT_CLIENT_TOKEN=…`), guarded "skip-if-empty" exactly like the
   `APP_STORE_CONNECT_*` skip pattern, so an unset secret keeps the dark state.
2. **Local dev builds**: create a **gitignored** `ios/Aurion/Secrets.xcconfig` defining
   `MWDAT_META_APP_ID = …` and `MWDAT_CLIENT_TOKEN = …`, set as the target's
   `baseConfigurationReference`. (Add `Secrets.xcconfig` to `.gitignore` — `*.xcconfig` secrets must
   never be committed.) The plist already reads `$(MWDAT_META_APP_ID)` / `$(MWDAT_CLIENT_TOKEN)` /
   `$(DEVELOPMENT_TEAM)`.
3. The plist `MWDAT` dict already has `MetaAppID`/`ClientToken`/`TeamID`; **`AppLinkURLScheme` is
   currently empty** — set it to `aurion://` (the scheme registered in step 5).

## Info.plist keys still to add (Phase 1 finalization, code — do with the credential wiring)

`ios/Aurion/Aurion-Info.plist` is still missing these MWDAT-required keys (confirmed against the
live iOS integration doc) — add them in the same PR that wires the credentials:

- `MWDAT` dict → add **`DAMEnabled` = `true`** (Device Access Toolkit App Model).
- **`UISupportedExternalAccessoryProtocols`** = `["com.meta.ar.wearable"]`.
- **`UIBackgroundModes`** → add `bluetooth-peripheral`, `external-accessory`.
- **`NSBluetoothAlwaysUsageDescription`** (Bluetooth link to the glasses).
- **`NSCameraUsageDescription`** — verify it exists (camera capture); add if absent.
- Set **`AppLinkURLScheme`** = `aurion://`.
- Build setting: add **`-traditional-cpp`** to Info.plist preprocessing so the `://` suffix survives
  (per Meta's iOS doc).

---

## Definition of done (Phase 0)

- [ ] Aurion org registered on the Wearables Developer Center; Developer Terms accepted.
- [ ] Developer-preview/partner access granted for `com.aurionclinical.physician`.
- [ ] `MetaAppID` + `ClientToken` obtained and handed off via the secret channel.
- [ ] App-link scheme (`aurion://`) + MFi string (`com.meta.ar.wearable`) confirmed.
- [ ] Release channel created; internal-TestFlight viability for the ExternalAccessory build confirmed.
- [ ] Pilot-physician tester tier decided (internal vs external).

When all boxes are checked, **Phase 3** (implement `MetaWearablesSource` for real) is unblocked —
keep `meta_wearables_enabled` OFF in AppConfig until on-device validation with a real pair.
