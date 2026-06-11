# Runbook — adding the AurionWatch target (#65)

> ✅ **DONE (2026-06-11).** The watchOS target **"AurionWatch Watch App"**
> was created in Xcode and committed, and the source was reconciled: the
> hand-written watch files now live in `ios/Aurion/AurionWatch Watch App/`
> (the target's synchronized folder), Xcode's stub `ContentView.swift` was
> removed, and the watch target carries its own byte-identical copy of the
> `WatchMessage` wire contract (the iOS and watch apps are separate modules
> — see the ⚠️ banner in both `WatchMessage.swift` files). Verified:
> `xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build`
> → **BUILD SUCCEEDED** (builds the iOS app **and** the embedded watchOS app),
> and the `AurionTests` watch/accent suites pass. The Embed Watch Content
> phase + `WKCompanionAppBundleIdentifier = com.aurionclinical.physician`
> are wired, so the watch app ships inside the iOS app's single TestFlight
> build.
>
> **Remaining (human):** (1) on-device verification per `docs/plans/watch-companion.md` §10;
> (2) watch `Localizable.strings` (EN+FR) — copy goes through `WL()`;
> (3) optional cleanup — Xcode also created `AurionWatch Watch AppTests`/`UITests`
> stub targets (Testing System wasn't set to None); harmless, delete in Xcode if undesired.

The sections below are the original creation steps, kept for reference.

---

This PR ships **all the source** for the Apple Watch companion (phone-side
bridge + the watchOS app's Swift files) plus device-independent unit tests.
The one step that **must be done in Xcode by a human** is creating the
watchOS app target — `project.pbxproj` is intentionally NOT hand-edited
(that risks the pilot's iOS build; see `docs/plans/watch-companion.md` §2).

Do these steps once, on the branch, before the on-device test (§10 of the
design doc).

## 1. Create the watch app target

1. Open `ios/Aurion/Aurion.xcodeproj` in Xcode 26+.
2. **File ▸ New ▸ Target… ▸ watchOS ▸ App.**
   - Product Name: **AurionWatch**
   - Interface: **SwiftUI**, Language: **Swift**
   - Bundle Identifier: `com.aurionclinical.physician.watchkitapp`
   - "Watch App for Existing iOS App" → companion app
     `com.aurionclinical.physician`.
   - Set **WATCHOS_DEPLOYMENT_TARGET** to the current minimum (watchOS 11+).
3. When Xcode offers to create `AurionWatchApp.swift` / `ContentView.swift`
   for the new target, **delete the generated stubs** — this PR already
   provides them under `ios/Aurion/AurionWatch/`.

## 2. Point the new target at the committed source

The watch source already lives at `ios/Aurion/AurionWatch/`:

```
AurionWatch/
  AurionWatchApp.swift            # @main App
  WatchConnectivityClient.swift   # WCSession client (receive state / send commands / haptics)
  Views/WatchTheme.swift          # brand tokens + WL() localized-string helper
  Views/RootView.swift            # state-driven router
  Views/ConsentView.swift         # 3 consent methods
  Views/ControlsView.swift        # pause/resume + stop
  Views/ElapsedView.swift         # local elapsed timer
```

- Make the new target's group a **synchronized folder reference** to
  `ios/Aurion/AurionWatch/` (right-click the group ▸ "Add Files…" or set
  the target's file-system-synchronized root), so these files are members
  of **AurionWatch** and stay auto-synced like the iOS app's group.

## 3. Share the message-shapes file with BOTH targets

`ios/Aurion/Aurion/Watch/WatchMessage.swift` is the single source of the
control-message shapes. It lives in the **iOS app**'s synchronized group
(so the phone-side bridge compiles today). Add it to the **AurionWatch**
target too:

- Select `WatchMessage.swift` ▸ File Inspector ▸ **Target Membership** ▸
  check **AurionWatch** (in addition to Aurion).
- It imports only `Foundation`, so it compiles unchanged on watchOS.

## 4. Embed so it ships in one TestFlight build

- On the **Aurion** (iOS) target ▸ Build Phases, confirm an **Embed Watch
  Content** phase carries **AurionWatch** (Xcode adds this automatically
  for a companion app). This makes the existing `ios-testflight.yml`
  package both in a single build — consistent with the bundle-into-one-build
  rule.

## 5. Watch localization (before pilot)

The watch copy goes through `WL(key, englishDefault)` (see `WatchTheme.swift`).
Add an `AurionWatch/Localizable.strings` (EN) + `fr.lproj/Localizable.strings`
(FR) at parity with the keys used (search `WL(` in the watch sources). This
satisfies the EN+FR parity rule for the new surface.

## 6. On-device verification (design doc §10)

WCSession reachability + haptics aren't faithful in the simulator. On a
paired iPhone + Apple Watch:

1. Watch app installs via the iOS build.
2. Consent from the wrist → phone writes the consent audit event → record unblocks.
3. Start / Pause / Resume / Stop from the wrist; state + elapsed match the phone within ~1s.
4. Haptics fire on each transition.
5. Disconnect mid-recording → phone keeps recording → reconnect resyncs.
6. Stop disabled until the minimum-recording floor.

## What's already verified (no device needed)

- Phone-side compiles into the iOS target (`WatchMessage`, `WatchSessionBridge`,
  the `ContentView` wiring).
- `AurionTests/WatchCompanionTests.swift` — message codec round-trips +
  the haptic-cue state-delta mapping.
