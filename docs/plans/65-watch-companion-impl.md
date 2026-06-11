## Task
#65 Apple Watch companion — implementation (control-only wrist remote) +
#418 iOS accent (bundled: both ship in one TestFlight build per CTO note).

## Why
#65: control capture from the wrist (consent / start / stop / pause /
resume + state + elapsed + haptics) without taking the phone out — a
wearable-first fit. Design: docs/plans/watch-companion.md.
#418 iOS accent: complete the personalization umbrella on iOS (portal
slice shipped in #425); the watch + iOS accent bundle into the same build.

## Approach
### #65 (control-only; phone is the source of truth)
- Shared `WatchMessage.swift` (in the iOS synchronized group so the phone
  side compiles now; add to the watch target's membership in Xcode):
  WatchCommand / WatchCommandMessage / WatchSessionState / WatchHapticCue —
  all non-PHI control values.
- Phone `WatchSessionBridge` (WCSessionDelegate, @MainActor): maps wrist
  commands to the SAME SessionManager path (audit included; consent NOT
  bypassed), validates against current state, publishes WatchSessionState
  via applicationContext on every transition + a haptic cue. Wired in
  ContentView next to the SessionManager StateObject. Dormant (OS no-op)
  without a paired watch.
- watchOS app (AurionWatch/): WCSession client + RootView state router +
  Consent / Controls / Elapsed views + brand WatchTheme. Elapsed computed
  locally from startedAtEpoch; Stop gated on canStop.
- Target created in Xcode by a human (File ▸ New ▸ Target) — pbxproj NOT
  hand-edited. Handoff: docs/runbooks/watch-companion-xcode-setup.md.

### #418 iOS accent (mirror the portal)
- `AurionAccent` palette (gold/teal/indigo/rose/slate) mirroring the web
  globals.css scales; gold = exact brand values (byte-identical default).
- Theme gold tokens (aurionGold/Light/Dark/Bg + gold gradients) become
  computed, reading `AurionAccent.current` (UserDefaults) — recolors every
  gold-token surface at once, like the portal CSS-variable swap. Token
  name kept `aurionGold` (rename = deferred codemod).
- AppState.accentColor (persisted) synced from profile.accent_color on
  load; ProfileView swatch picker PUTs accent_color (cross-device w/ portal).
- Compliance colors (amber/red/green/blue, navy) are separate tokens —
  untouched.

## Acceptance criteria
- [ ] AC-1: phone-side compiles into the iOS app target (build succeeds).
- [ ] AC-2: WatchMessage codecs + bridge haptic-cue mapping unit-tested.
- [ ] AC-3: #418 gold default is byte-identical to brand (unit-tested);
      picker changes accent locally + PUTs.
- [ ] AC-4: AurionTests green; EN+FR parity for new iOS strings.
- [ ] AC-5 (human, on-device): watch target created + §10 device test.

## Out of scope
- watchOS target creation + on-device WCSession/haptics verification (human).
- Watch Localizable.strings EN/FR (drop-in after the target exists; copy
  goes through WL()).
- Standalone watch, complications, watch Live Activity.
- gold→accent token rename (deferred codemod); decorative gold hex that
  isn't on the gold token.

## Test plan (executable)
1. xcodebuild -scheme Aurion -sdk iphonesimulator build → BUILD SUCCEEDED
2. xcodebuild test -scheme Aurion -only-testing:AurionTests/{AurionAccent,WatchCommandMessage,WatchSessionState,WatchHapticCue}Tests

## Security implications
- PHI: the watch receives only control fields (state string, consent bool,
  elapsed anchor, canStop) — no transcript/note/identifier/frames.
- Consent gate preserved: the watch triggers `confirmConsent` (which writes
  the audit event); it does not bypass the record-hard-block.
- WCSession traffic is device-local; nothing transits the backend.
