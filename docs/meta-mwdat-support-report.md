# MWDAT support report — glasses never reach `registered`

**Status:** open · filed with Meta Wearables (DAT) support
**Last verified:** 2026-08-14

> **Subject line for the ticket:** MWDAT — glasses never reach registered; audio session drops, video source never connects (Ray-Ban Meta Gen 1, iOS)

## Summary

A third-party iOS app integrating the Wearables Device Access Toolkit cannot complete device
registration. The consent flow succeeds and the app is authorized, but the SDK never transitions
to a registered/streaming state, and the glasses' audio/video routes are not exposed to the app.
Every documented prerequisite is satisfied and verified.

## Environment

| | |
|---|---|
| Project | Aurion Clinical — ID `1899666440990640` |
| Release channel | "Aurion pilot testers", version **1.0.1**, build status **Ready**, published to channel |
| Tester account | `faical.sawadogo@aurionclinical.com` — **Active user** (0 pending / 0 revoked) |
| Meta AI app | iOS, version **285.0.0.16.165**, signed into the same allowlisted account |
| Developer Mode | **Enabled** (Settings → App Info) |
| Glasses | **Ray-Ban Meta Wayfarer (Gen 1)**, device name **RB Meta 00K4**, battery 97% |
| DAT SDK on device | **0.9.0.26.0** — shown with a green/active indicator under App Info |
| iOS app | Bundle ID `com.aurionclinical.physician`, Team ID `2W2Z75Q5ZA` |
| Universal Link | `https://portal.aurionclinical.com/wearables/auth` — AASA served (HTTP 200) and includes this path for the above app ID |
| Required actions | None outstanding on the project |

## What works

1. `Wearables.configure()` succeeds — the SDK initializes with the project's MetaAppID +
   ClientToken (no configuration error).
2. Tapping Connect in our app opens the Meta AI authorization sheet:
   **"Connect PeriTwin to your Meta devices?"** with the Unverified App toggle enabled.
3. Tapping **Connect** on that sheet completes without error and returns to our app.
4. At one point after enabling Developer Mode, our app briefly showed the glasses as an available
   **audio** source ("RB Meta 00K4 — Connected"), confirming the SDK can enumerate the device.

## What fails

- The SDK connection state never reaches **registered**. Our diagnostic readout stays at
  *"SDK ready · glasses not registered yet"*.
- The **video source (glasses camera) never connects** — it remains "Disconnected" both before and
  after the authorization consent is granted.
- The audio route the app briefly saw **disappeared** after the authorization round-trip and has
  not returned; the app now reports no Bluetooth audio device.
- Critically: **iOS Settings → Bluetooth shows "RB Meta 00K4 — Connected"** at the same moment our
  app reports the device as disconnected. The OS-level link is up while the SDK exposes nothing.

## Earlier failure mode (now changed)

Before Developer Mode was enabled, the same flow returned a modal reading
**"Internal error — The operation could not be completed"** at the authorization step. Enabling
Developer Mode replaced that error with the proper consent sheet, so the error was gated on
Developer Mode — but registration still does not complete.

## Already ruled out

- **Credentials** — MetaAppID/ClientToken current from Developer Center; SDK configures successfully.
- **Allowlist** — tester is Active on the channel the published version targets.
- **Version mismatch** — app and channel both on 1.0.1.
- **Universal Link / AASA** — verified live (HTTP 200) and correctly scoped to
  `2W2Z75Q5ZA.com.aurionclinical.physician`.
- **Account mismatch** — Meta AI is signed into the allowlisted account.
- **Developer Mode** — enabled, and the app registers as a developer-mode app.
- **Hardware support** — Gen 1 Ray-Ban Meta is listed as supported.
- **Device availability** — glasses connected at OS level, 97% battery, DAT SDK reporting green.

## Questions for Meta

1. Are there additional requirements beyond Developer Mode + release-channel membership for an
   unpublished app to reach the **registered** state and open a camera/video session?
2. Is there a **minimum glasses firmware version** for DAT SDK 0.9.0.26.0? If so, what is it and how
   do we verify/force the update? (Our glasses report no pending update in Meta AI.)
3. Is the **Ray-Ban Meta Gen 1** camera/video stream supported for third-party apps, or is video
   restricted to Gen 2 / Display models with Gen 1 limited to audio?
4. Is there a way to surface a specific error code from the registration attempt? The failure is
   currently silent on the app side and generic ("Internal error") on the Meta side, which leaves us
   with nothing to act on.

## Reproduction

Glasses on and awake → Meta AI closed → open our app → Devices → Connect Ray-Ban Meta → consent
sheet appears → accept → returns to app → connection state remains unregistered, video source
Disconnected.

## Internal notes (not part of the ticket)

- **Leading hypothesis: question 3.** Meta's own materials emphasise **Gen 2** for the
  camera/POV-streaming use case, and our glasses are **Gen 1**. That *audio* enumerated while
  *video* never has is consistent with a Gen 1 video restriction. If confirmed, the fix is hardware
  (a Gen 2 pair), not code — decide this before the pilot depends on glasses video.
- **Do not "fix" the Universal Link domain.** `portal.aurionclinical.com` is pinned deliberately for
  the iOS Universal Link + this Meta app-link, and is kept live alongside `portal.peritwin.com` on
  the same Amplify app. Repointing it to the peritwin domain would force iOS to re-verify the
  association and risks breaking a flow that currently works.
- App-side state is instrumented: the Devices screen shows a diagnostic line mapping
  `MWDATManager.connection` (`unavailable` → "SDK inactive" / `available` → "SDK ready" /
  `registering` / `registered`). Use it to report state precisely in any follow-up.
