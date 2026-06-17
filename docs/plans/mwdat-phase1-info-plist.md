# Plan — MWDAT Phase 1 finalization (Info.plist + credential wiring)

## Task
mwdat-phase1 — finalize the MWDAT app configuration so the Ray-Ban Meta glasses
integration is fully wired and ready to activate, while the SDK stays dark.

## Why
Unblocks the glasses path (CLAUDE.md "Audio is the spine, video is the flesh";
plan `~/.claude/plans/zazzy-dreaming-galaxy.md`). Phase 0 (Meta project) is done by
Faïçal; Phases 1 (#442) & 2 (#440) landed the SDK link, `Wearables.configure()`,
the Universal-Link infra (AASA + entitlement + handler), the usage strings, and the
`VideoClipSource` refactor. The MWDAT `Info.plist` dict is still missing the keys the
toolkit requires per the live Meta iOS integration doc, and `AppLinkURLScheme` is empty.

## Approach
Edit `ios/Aurion/Aurion-Info.plist` only (config; no Swift). `GENERATE_INFOPLIST_FILE=YES`
merges the pbxproj `INFOPLIST_KEY_*` usage strings (already present, incl. a Ray-Ban-Meta
Bluetooth string) with this hand-written plist.
- Set `MWDAT.AppLinkURLScheme` = `https://portal.aurionclinical.com/wearables/auth`
  (the Universal Link Faïçal registered in the Wearables Developer Center; matches the
  shipped AASA path + the `applinks:portal.aurionclinical.com` entitlement).
- Add `MWDAT.DAMEnabled` = `true` (Device Access Toolkit App Model).
- Add `UISupportedExternalAccessoryProtocols` = `[com.meta.ar.wearable]`.
- Add `UIBackgroundModes` = `[bluetooth-peripheral, external-accessory]`.
- CI: inject `MWDAT_META_APP_ID` / `MWDAT_CLIENT_TOKEN` (GH secrets) as build settings on the
  archive step in `ios-testflight.yml`, **skip-if-empty** (mirrors the `APP_STORE_CONNECT_*`
  guard) — empty secrets keep the dark state. Developer Mode needs no creds.
- Fix the Phase 0 runbook's stale `aurion://` → the Universal Link URL.

## Acceptance criteria
- [ ] AC-1: `plutil -lint ios/Aurion/Aurion-Info.plist` → "OK" (well-formed).
- [ ] AC-2: `MWDAT.AppLinkURLScheme` == `https://portal.aurionclinical.com/wearables/auth`.
- [ ] AC-3: `MWDAT.DAMEnabled` == true; `UISupportedExternalAccessoryProtocols` contains
  `com.meta.ar.wearable`; `UIBackgroundModes` contains `bluetooth-peripheral` + `external-accessory`.
- [ ] AC-4: iOS `build` check green (compiles for iPhone 17 sim + AurionTests pass) — proves the
  plist additions don't break the build. Verified by CI.
- [ ] AC-5: `MWDAT.MetaAppID`/`ClientToken` still read `$(MWDAT_*)` build vars (empty ⇒ dark).

## DRY / SOLID check
- **Existing helpers to reuse**: the MWDAT dict, `Wearables.configure()`, the AASA payload,
  the `applinks:` entitlement, and the `INFOPLIST_KEY_NS*UsageDescription` strings all already
  exist (#442) — this PR only adds the missing plist keys, introduces no new code/helpers.
- **New helper introduced?**: no.
- **iOS UI tasks only**: n/a (no UI; config only).

## Out of scope
- Implementing `MetaWearablesSource` for real (Phase 3 — blocked on Meta credentials).
- Flipping `meta_wearables_enabled` (stays OFF until on-device validation).
- Adding the actual MetaAppID/ClientToken values (Developer Mode needs none; secrets land later).

## Test plan (executable)
1. `plutil -lint ios/Aurion/Aurion-Info.plist` → OK
2. `/usr/libexec/PlistBuddy -c 'Print :MWDAT:AppLinkURLScheme' ios/Aurion/Aurion-Info.plist`
3. CI iOS `build` job (iPhone 17 compile + AurionTests) → green
4. `grep -c com.meta.ar.wearable ios/Aurion/Aurion-Info.plist` → ≥1

## Security implications
- No PHI, no secrets in git (creds remain `$(MWDAT_*)` build vars; GH-secret-sourced, skip-if-empty).
- No AI prompt, no audit-log, no consent-gate change. Masking path untouched.
- **Distribution:** `UISupportedExternalAccessoryProtocols` + `external-accessory` background mode
  declare the app as an MFi/ExternalAccessory app → **external-TestFlight Beta App Review may reject**.
  Decision (Faïçal, 2026-06-16): include now; the **next external TestFlight dispatch must go
  internal-only** (`TESTFLIGHT_INTERNAL_ONLY`). Glasses build is internal-only by design.
