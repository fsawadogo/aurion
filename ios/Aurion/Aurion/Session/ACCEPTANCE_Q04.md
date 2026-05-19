# Q-04 — SessionUIState shim cleanup (Acceptance)

## Goal

Drop the three Bool read-only shims on ``SessionManager``
(``isProcessing``, ``showingReview``, ``showingPostEncounter``) that
Phase 4 left in place to avoid changing every SwiftUI call site in the
same PR. ContentView's dispatch cascade now reads ``uiState`` directly,
matching the design comment on ``SessionManager.uiState``.

## Scope

- `ios/Aurion/Aurion/App/ContentView.swift` — three readers + three
  `.animation(value:)` modifiers migrate to ``uiState``.
- `ios/Aurion/Aurion/Session/SessionManager.swift` — drop lines 82-87
  (the shims). Stale "Keep isProcessing true" comments updated.
- `ios/Aurion/Aurion/Session/SessionUIState.swift` — trim the
  "Mapping to the prior booleans" docblock now that the booleans are
  gone.

## Out of scope

- The cascade's structure stays an if/else-if chain rather than a
  ``switch sessionManager.uiState``. Two branches still combine state
  with optional binding (``if uiState == .reviewing, let note =
  ...``), which doesn't translate cleanly to a single switch. Three
  equality checks is fine.
- VoiceProcessingView's local ``@State private var isProcessing`` is
  unrelated to SessionManager — left untouched.

## Acceptance

```bash
grep -rn 'isProcessing\|showingReview\|showingPostEncounter' \
  ios/Aurion --include="*.swift" \
  | grep -v VoiceProcessingView
# → empty (the only remaining `isProcessing` is the @State local in
#   VoiceProcessingView)

xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build
xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M4)' build
```

## DRY / SOLID gates

- **DRY:** one source of truth for "what screen are we on?" — the
  ``uiState`` enum. Three computed shims gone.
- **SRP:** ``SessionManager`` is the state owner; ContentView is the
  router. No double abstraction between them.
- **DIP:** ContentView depends on the ``SessionUIState`` enum (an
  abstraction) not on a constellation of bools.
