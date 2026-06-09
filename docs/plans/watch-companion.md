# Apple Watch Companion — Design

**Issue:** #65 · **Status:** Post-MVP, design-only (implementation deferred until an Apple Watch is in the testing loop) · **Area:** iOS / watchOS

> A wrist remote for capture: **confirm consent, start / stop / pause / resume**, see **recording state + elapsed**, and feel **haptic cues** — without taking the phone out. Control-only: the watch never captures audio/video or shows patient content. It drives the phone's existing session state machine over WatchConnectivity.

---

## 1. Scope

**In scope (per #65):**
- Consent confirmation from the wrist.
- Start / Stop / Pause / Resume.
- Live recording state + elapsed timer on the watch.
- Haptic cues on state transitions.

**Out of scope (explicitly):**
- Audio/video capture on the watch (the phone + Ray-Ban Meta wearable remain the capture devices).
- Any patient content on the watch — no transcript, no note, no identifiers, no frames (PHI-never-on-the-watch; see §7).
- Standalone (phone-less) operation, complications, Live Activity on watch — possible later, not now.

**Non-goals that the architecture must still respect:**
- The record action is **hard-blocked until `consent_confirmed` is in the audit log** (CLAUDE.md). The watch is just another trigger for the *same* `SessionManager.confirmConsent(...)` path — it must not bypass the gate.
- Descriptive-mode and all pipeline behavior are unchanged; the watch only sends control intents.

---

## 2. Target structure

- New watchOS **app** target `AurionWatch` (modern single-target watch app; no separate WK extension needed on current watchOS).
- Companion to the physician app: `WKCompanionAppBundleIdentifier = com.aurionclinical.physician`; watch bundle id `com.aurionclinical.physician.watchkitapp`.
- `WATCHOS_DEPLOYMENT_TARGET` = the current min (watchOS 11+; align with the iOS 26 baseline).
- The watch app is **embedded in the iOS app** (Embed Watch Content build phase) so it ships in the same TestFlight build — see §8.
- **Created in Xcode** (File ▸ New ▸ Target ▸ Watch App), NOT by hand-editing `project.pbxproj` (that risks the pilot's iOS build). The Swift files below drop into the new target.

```
ios/Aurion/
  Aurion/                     # existing iOS app
    Watch/                    # NEW (phone side)
      WatchSessionBridge.swift
  AurionWatch/                # NEW watchOS app target
    AurionWatchApp.swift
    WatchConnectivityClient.swift
    Views/{ConsentView,ControlsView,ElapsedView,RootView}.swift
  Shared/
    WatchMessage.swift        # NEW — message shapes shared by both targets
```

---

## 3. Transport — WatchConnectivity (WCSession)

No App Group exists, and we don't need a shared file container — only small control messages + a tiny state object. WCSession is the right (and only) fit.

| Need | API | Why |
|---|---|---|
| Phone → watch **state** (current state, consent flag, started-at) | `updateApplicationContext` | Latest-wins, coalesced, **survives disconnect** — the watch always sees the freshest state on reconnect/launch. |
| Watch → phone **commands** (consent/start/stop/pause/resume) | `sendMessage(_:replyHandler:)` when `isReachable`, else `transferUserInfo` | Commands need delivery + an ack; reachable → immediate with reply, else queued. |
| Phone → watch **haptic** triggers | `sendMessage` (fire-and-forget) when reachable | Transient; if the watch isn't reachable a haptic is moot. The watch ALSO derives haptics locally from state deltas (see §6) so a missed message still feels right. |

Both sides activate one `WCSession` at launch (`WCSession.default`, set `delegate`, `activate()`), guarded by `WCSession.isSupported()`.

### Message shapes (`Shared/WatchMessage.swift`, in both targets)

```
// watch → phone
enum WatchCommand: String, Codable { case confirmConsent, start, pause, resume, stop }
struct WatchCommandMessage: Codable { let command: WatchCommand; let consentMethod: String? } // consentMethod set only for .confirmConsent

// phone → watch (applicationContext)
struct WatchSessionState: Codable {
  let state: String          // SessionState.rawValue (IDLE/CONSENT_PENDING/RECORDING/PAUSED/…)
  let consentConfirmed: Bool
  let startedAtEpoch: Double? // wall-clock anchor for the watch's local elapsed timer
  let canStop: Bool          // mirrors the phone's minimum-recording-duration gate
}
```

Keys are non-PHI control values only.

---

## 4. Phone side — `WatchSessionBridge`

A `WCSessionDelegate` (an `ObservableObject` owned by the app) that:
- On `didReceiveMessage`/`didReceiveUserInfo`: decode `WatchCommandMessage`, **hop to `@MainActor`**, and call the matching `SessionManager` method:
  - `.confirmConsent` → `confirmConsent(method:)` (writes the consent audit event — the watch does NOT bypass the gate)
  - `.start` → `startRecording()`
  - `.pause` → `pauseRecording()`, `.resume` → `resumeRecording()`, `.stop` → stop
- Observes `SessionManager.$session` (state) and pushes a fresh `WatchSessionState` via `updateApplicationContext` on **every transition** + once on activation.
- Sends a haptic-trigger message on the transitions that warrant one (§6).

`SessionManager` is `@MainActor`; the WCSession delegate callbacks arrive off the main thread, so every command handler wraps the call in `Task { @MainActor in … }`. The bridge is created in `AurionApp` alongside the other app-scoped singletons and given the `SessionManager` reference.

Commands are **validated against current state** before dispatch (e.g. ignore `.start` if not `CONSENT_PENDING`/idle, ignore `.stop` if `!canStop`) so a stale watch tap can't drive an illegal transition — `SessionManager` already throws `InvalidTransitionError`, which the bridge swallows + re-pushes the true state so the watch re-syncs.

---

## 5. Watch side — UI

`RootView` switches on the latest `WatchSessionState.state`:

| State | Watch screen |
|---|---|
| no session / `IDLE` | "Open Aurion on iPhone to start a session" (the session is created on the phone's context sheet; the watch doesn't pick specialty/visit-type) |
| `CONSENT_PENDING` | **ConsentView** — the 3 `ConsentMethod`s (Verbal / Paper / Digital) as large tap targets → `confirmConsent(method)` |
| `RECORDING` | **ControlsView** — big Pause + Stop; **ElapsedView** timer running |
| `PAUSED` | Resume + Stop; elapsed frozen |
| `PROCESSING_*` / `AWAITING_REVIEW` / terminal | "Processing on iPhone…" / "Review on iPhone" (read-only) |

- **Elapsed** is computed locally from `startedAtEpoch` (a `TimelineView(.periodic)` ticking each second) so it's smooth without a message per second; re-anchored whenever a new context arrives.
- **Stop** is disabled until `canStop` (mirrors the phone's `minimumRecordingSeconds` gate) so the watch can't stop a session before the first buffers land.
- Buttons disable optimistically on tap and re-enable when the next state context confirms the transition (avoids double-fire on a laggy link).

---

## 6. Haptics

`WKInterfaceDevice.current().play(_:)` on:
- consent confirmed → `.success`
- recording started → `.start`
- paused → `.directionUp`, resumed → `.start`
- stopped → `.stop`
- link lost mid-recording → `.failure` (so the clinician knows the wrist remote is no longer authoritative)

The watch derives these from **state deltas it observes locally** (comparing the new context to the last), so haptics are correct even if a dedicated haptic message is dropped. The phone's explicit haptic message is a belt-and-suspenders for immediacy.

---

## 7. Privacy / security (Law 25 / descriptive-mode posture)

- **No PHI on the watch, ever.** The watch receives only: session *state* string, a consent-confirmed bool, an elapsed anchor, and a `canStop` bool. No transcript, note, identifier, specialty-as-PHI, or frames. This is the hard rule that keeps the watch out of scope for the PHI surface.
- Consent **method** (verbal/paper/digital) is not PHI; sending it is fine. Consent itself is still recorded by the phone's `confirmConsent` → audit event — the watch is a trigger, not a new consent authority.
- WCSession traffic is device-local + encrypted by the OS; nothing transits Aurion's backend.
- The record-hard-block invariant is preserved: `startRecording()` on the phone still refuses until `consent_confirmed`; the watch just surfaces the consent step earlier.

---

## 8. Build / distribution

- The watch app is embedded in the iOS app, so the existing `ios-testflight.yml` build packages it automatically — **one TestFlight build carries both** (consistent with the bundle-into-one-build rule). No separate pipeline.
- First build after the target is added: confirm the watch app appears in the build and installs to the paired watch via the phone's Watch app.
- Distribute to the same groups (Aurion Internal + Pilot Physicians).

---

## 9. Edge cases

- **Watch app not running / not installed:** phone behaves exactly as today; `updateApplicationContext` is queued and delivered when the watch app next launches.
- **Link drops mid-recording:** the phone keeps recording (it's the source of truth); the watch shows a "disconnected" state + `.failure` haptic; on reconnect it resyncs from the latest applicationContext.
- **Phone backgrounded:** WCSession still delivers; `SessionManager` runs in the existing background-capable capture session.
- **Stale command race:** handled by state-validation in the bridge (§4) — illegal transitions are ignored and the true state is re-pushed.
- **Two triggers (watch + phone) at once:** both call the same `@MainActor SessionManager`; serialized on the main actor; the state machine rejects the redundant one.

---

## 10. Test plan (on-device — required)

WCSession reachability + haptics are not faithfully testable in the simulator, so verification needs a paired iPhone + Apple Watch:
1. Pairing + watch-app install via the iOS build.
2. Consent from the watch → phone audit event written → record unblocks.
3. Start/Pause/Resume/Stop from the wrist; state + elapsed match the phone within ~1s.
4. Haptics fire on each transition.
5. Disconnect (walk away / airplane mode on watch) mid-recording → phone keeps recording → reconnect resyncs.
6. Stop disabled until the minimum-recording floor.

Unit-testable without a device: `WatchSessionState`/`WatchCommandMessage` codec round-trips, the bridge's command→SessionManager mapping (mock `SessionManager`), and the state-validation guards.

---

## 11. Decisions to confirm before building

1. **Consent on the watch:** offer all 3 methods, or just "Verbal" (the common in-room case) with the others on the phone? (Leaning: all 3 — they're one tap each.)
2. **Session creation:** keep it phone-only (watch can't pick specialty/visit-type/context), or add a "quick start" with the physician's default template? (Leaning: phone-only for v1 — the context sheet is where specialty/visit-type/clinical context is chosen.)
3. **watchOS minimum** version (drives available APIs/haptics).
4. **Pilot fit:** the pilot wearable is Ray-Ban Meta, not Apple Watch — confirm a watch is actually in the pilot loop before prioritizing the implementation (this is why it's post-MVP).
