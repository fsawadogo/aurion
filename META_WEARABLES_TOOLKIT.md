# Meta Wearables Device Access Toolkit — Aurion Integration Brief

**Status:** Public developer preview. Aurion has not yet applied.
**Last verified:** 2026-05-06

---

## What it is

Meta's official SDK for piping camera and microphone streams from Ray-Ban Meta
and Oakley Meta HSTN smart glasses back to a paired iOS or Android app. This is
the gate that unblocks `MetaWearablesSource.start()` in `ios/Aurion/Capture/`
— the BLE pairing layer is already wired (see `BLEPairingManager.swift`) but
the actual video stream subscription requires this toolkit.

## Supported hardware

- Ray-Ban Meta — Gen 1
- Ray-Ban Meta — Gen 2
- Oakley Meta HSTN

## Access tiers

| Tier | What you can do |
|---|---|
| **Developer preview** (current) | Build, prototype, ship to **internal testers within your org / Meta-approved test group** |
| **Publish to broader community** | Limited to select partners during preview. Broader rollout planned through 2026. |

> **Pilot impact:** During preview Aurion can only deploy to clinicians enrolled
> as internal testers. Public TestFlight or App Store distribution with the
> wearables integration is gated on Meta promoting Aurion from preview → publish.

## Application links

| Purpose | URL |
|---|---|
| **Apply for preview access (the form)** | https://developers.meta.com/wearables/notify/ |
| Developer center — setup + docs | https://wearables.developer.meta.com/docs/getting-started-toolkit/ |
| FAQ — gating, capabilities, restrictions | https://developers.meta.com/wearables/faq/ |
| Announcement blog post | https://developers.meta.com/blog/introducing-meta-wearables-device-access-toolkit/ |
| Industry coverage — UploadVR | https://www.uploadvr.com/meta-wearables-device-access-toolkit-public-preview/ |
| Industry coverage — Road to VR | https://www.roadtovr.com/meta-ray-ban-smart-glasses-third-party-app-sdk-device-access-toolkit/ |
| Industry coverage — Auganix | https://www.auganix.org/ar-news-meta-wearable-device-sdk/ |
| Community forum thread | https://communityforums.atmeta.com/discussions/Questions_Discussions/meta-glasses-sdk-access/1358961 |

## What to put in the application

Lead with use-case clarity — Meta gates approval partly on having a credible,
non-generic pitch:

- **Company:** Aurion Clinical AI
- **Product:** Wearable multimodal AI physician assistant
- **Use case:** Hands-free clinical documentation — glasses capture
  visual context (physical exam findings, imaging on screen) which gets paired
  against the audio transcript to produce SOAP-structured notes
- **Mode:** Descriptive-only — Aurion never diagnoses or interprets. The model
  documents what was observed; the physician retains all clinical judgment.
- **Pilot:** CREOQ / CLLC — Dr. Perry Gdalevitch (plastic surgeon) +
  Dr. Marie Gdalevitch (orthopedic surgeon), 3–5 clinicians
- **Privacy posture:** PHI never in logs / errors / S3 keys. Faces masked
  on-device before any frame leaves iOS. Audio purged after transcription.
- **Existing iOS scaffolding:** BLE pairing layer already implemented; the
  Wearables Toolkit is the bounded addition needed to subscribe to video
  frames from the glasses' camera.

## Integration plan once approval lands

The swap is bounded — the rest of the app talks to `MetaWearablesSource` only
through the `CaptureSource` API, so no callers need refactoring.

1. **Drop the framework** in `ios/Aurion/Frameworks/`
   ```
   MetaWearables.xcframework
   ```

2. **Add to the Xcode target** — Embed & Sign

3. **Update entitlements / Info.plist** for the toolkit's required keys
   (privacy strings for camera relay, background modes if streaming continues
   while screen is off — exact list comes from the toolkit setup guide)

4. **Replace the stub in `MetaWearablesSource.start()`**
   Current state (`ios/Aurion/Capture/MetaWearablesSource.swift`):
   ```swift
   override func start() throws {
       guard RemoteConfig.shared.featureFlags.metaWearablesEnabled else {
           throw CaptureSourceError.featureGated("Meta Wearables")
       }
       guard BLEPairingManager.shared.isPaired else {
           throw CaptureSourceError.notImplemented
       }
       // TODO(meta-sdk): MetaWearables.shared.subscribeVideo(fps: 1) { ... }
       throw CaptureSourceError.notImplemented
   }
   ```
   After approval: replace the `throw` with the toolkit's `subscribeVideo`
   callback that pushes frames into the existing capture pipeline.

5. **Discovery flow** — decide whether to keep `BLEPairingManager` as the
   primary pairing UX or hand off to `MetaWearables.shared.discoverAvailableDevices()`.
   The toolkit may insist on its own pairing handshake (likely, since Meta
   gates connection on Meta account auth). If so, `WearableSetupView` becomes
   a thin wrapper around the toolkit's UI.

6. **Flip the feature flag** — `meta_wearables_enabled = true` in AppConfig.
   `MetaWearablesSource.applyCurrentAvailability()` already handles the
   `(flagOn, paired)` branch correctly: `.ready · 1080p · 60 fps`.

## What CAN'T be done with the toolkit (still)

Per the FAQ — worth knowing before pilot scope creeps:

- **No third-party publish to broader community during preview** — Aurion stays
  in invite-only test distribution until promoted.
- **Audio from the glasses still goes through Bluetooth Classic (A2DP/HFP).**
  The toolkit exposes microphone capture but iOS routes glasses audio as a
  system mic input regardless — handled today by `BluetoothAudioSource`.
- **No on-glasses display rendering** in Ray-Ban Meta (no display on Gen 1/2).
  Oakley Meta HSTN is the same — capture-only device.
- **Background processing limits** — the toolkit operates while the host app
  is foregrounded or in a brief background window; not a 24/7 always-on stream.

## Open questions to resolve at signup

- [ ] Does Meta require an LLC / business entity before approving, or is a
      sole-developer / startup application accepted?
- [ ] Is there an NDA we sign before SDK download? (Affects what we can put
      in CLAUDE.md and design docs.)
- [ ] Per-device pairing limits — does each clinician's iPhone need its own
      Meta account, or can pairing be transferred across devices?
- [ ] Audit / telemetry requirements Meta imposes on partner apps using the
      camera stream (relevant to our `audit_log` module).
- [ ] Does the toolkit support paused/resumed video subscription (for our
      session pause/resume), or do we cycle the subscription on each transition?

## Cross-references

- iOS BLE pairing: `ios/Aurion/Aurion/Capture/BLEPairingManager.swift`
- iOS capture source: `ios/Aurion/Aurion/Capture/MetaWearablesSource.swift`
- iOS pairing UI: `ios/Aurion/Aurion/Onboarding/WearableSetupView.swift`
- Backend feature flag: `meta_wearables_enabled` in AppConfig schema
  (`backend/app/modules/config/schema.py`)
