# P1-4-FU: VideoRingBuffer Swift 6 forward-compat — actor-style isolation

**Parent plan:** `~/.claude/plans/dual-mode-visual-evidence.md` (P1-4 ships in PR
that introduced `VideoRingBuffer.swift`; this is the narrow forward-compat
follow-up.)

**Backlog item:** P1-4-FU iOS · Swap NSLock → actor for Swift 6 forward-compat.

## Why

`VideoRingBuffer.swift:175,177` calls `NSLock.lock()` / `unlock()` from the
async `extract(around:duration:)` method. Swift 6 strict-concurrency rejects
this: `NSLock`'s `lock` / `unlock` are marked unavailable from asynchronous
contexts (the runtime cannot reason about cooperative yields holding a
non-async-aware lock — risk of priority inversion and lost wakeups).

Compiler output today, under `-strict-concurrency=complete`:

```
VideoRingBuffer.swift:175:14: warning: instance method 'lock' is unavailable
  from asynchronous contexts; Use async-safe scoped locking instead; this is
  an error in the Swift 6 language mode
VideoRingBuffer.swift:177:14: warning: instance method 'unlock' is unavailable
  from asynchronous contexts; Use async-safe scoped locking instead; this is
  an error in the Swift 6 language mode
```

When the Aurion project flips to Swift 6 strict-concurrency mode (planned for
late pilot — tracked separately), these warnings become hard build errors.
This PR removes them now so the migration isn't blocked.

## Approach — Path B (`OSAllocatedUnfairLock<State>`)

Two clean Swift 6 paths exist; we took the second:

### Why not Path A (actor)

A pure-actor refactor (extract a `VideoRingBufferStorage` actor that owns
`entries` and gate every mutation through it) is the cleanest from a Swift 6
purity standpoint, but it introduces a real correctness risk for our specific
caller pattern:

1. `append(_:at:)` is called from AVFoundation's sample-buffer delegate
   callback — a nonisolated synchronous context with a strict ordering
   guarantee (sample buffers arrive in PTS order on a serial dispatch queue).
2. To call an actor's `append` from there we'd have to either
   `Task { await storage.append(...) }` (fire-and-forget, breaks ordering and
   risks dropped buffers under back-pressure) or hop the entire capture
   delegate to async (not possible — AVFoundation calls us synchronously).
3. Fire-and-forget Task spawning at 1 fps is cheap on its own, but extract
   would then see a snapshot that's racing the unprocessed Task queue —
   silently violating the contract "extract a window covering all appended
   frames".

### Why Path B (`OSAllocatedUnfairLock<State>`)

`OSAllocatedUnfairLock` is the Apple-recommended primitive for synchronous
critical sections callable from any isolation domain, including async
contexts. From the official docs (iOS 16+):

> A lock value type allocated by the system to provide unfair scheduling
> semantics. Designed to be safely used from both synchronous and
> asynchronous contexts.

Its `withLock` API is `@Sendable` and async-safe — Swift 6 strict-concurrency
accepts it without complaint. Holding it through a small synchronous critical
section (push + maybe pop-front, or copy-out the snapshot array) is exactly
its intended use case.

The state-owning generic form (`OSAllocatedUnfairLock<State>`) is doubly
useful: it encodes "the only mutable state in this class is the deque, and
the lock owns it" at the type level. The compiler refuses to access `entries`
outside the `withLock` closure — strictly stronger than the previous
"discipline" of remembering to call `lock()` before every read/write.

### Mechanical changes

- Replace `private let lock = NSLock()` + `private var entries: [Entry] = []`
  with `private let state = OSAllocatedUnfairLock<[Entry]>(initialState: [])`.
- Replace every `lock.lock() ... lock.unlock()` pair with
  `state.withLock { entries in ... }`.
- The `count` accessor, `append`, `clear`, and the snapshot-copy at the top
  of `extract` all use the same `withLock` pattern.
- `import os` for the `OSAllocatedUnfairLock` symbol.
- Class remains `final class ... : @unchecked Sendable`. The
  `OSAllocatedUnfairLock` itself is `Sendable`; the `@unchecked` annotation
  stays only because `CMSampleBuffer` is not `Sendable` and we hold them in
  the closed-over state. The closure-scoped access pattern guarantees no two
  threads observe `entries` at the same time, which is the actual safety
  property.

### What does NOT change

- Public surface of `VideoRingBuffer`: `init`, `count`, `append`, `clear`,
  `extract` — all identical signatures, identical semantics. **LSP** holds:
  `CaptureManager`, `BuiltInCaptureSource`, `SessionManager`, and
  `MaskingPipeline` all keep working unmodified.
- Privacy contract (CLAUDE.md "Privacy" §): raw `CMSampleBuffer` references
  still live in memory only, never persisted or transmitted unmasked. The
  comment header is extended with a note that the contract belongs at the
  lock-owned state boundary, not just at the class facade.
- All seven existing unit tests pass without modification.

## Acceptance criteria

- [ ] AC-1: `VideoRingBuffer.swift` emits **zero warnings** under
  `xcodebuild ... build OTHER_SWIFT_FLAGS='$(inherited) -strict-concurrency=complete'`.
  Other files may still emit warnings (deferred — see PR body).
- [ ] AC-2: `xcodebuild build` succeeds for iPhone 17 (iOS Simulator).
- [ ] AC-3: `xcodebuild build` succeeds for iPad Pro 11" M5 substitute
  (M4 may not be installable in the sandboxed env; M5 documented as
  substitution in the PR body).
- [ ] AC-4: All seven existing `VideoRingBufferTests` cases pass unmodified.
- [ ] AC-5: One new test `extract_underHeavyConcurrentAppendLoad` exercises
  100 concurrent appends through a `TaskGroup`, then extracts a covering
  window. Asserts no crash, MP4 valid, frames-in-MP4 ≤ buffer cap.

## DRY / SOLID check

- **Existing helpers to reuse:** There is no existing lock primitive in the
  iOS codebase (`grep` for `NSLock`, `OSAllocatedUnfairLock`, `os.lock`
  returns just this file). `OSAllocatedUnfairLock` is the standard Apple
  primitive; not a candidate for extraction.
- **New helper introduced?:** No. We replace one type with another inside
  the same class. No new file, no new helper. The bar for new abstractions
  stays met.
- **SRP:** `VideoRingBuffer` continues to do one thing — own the ring of
  raw sample buffers and offer a snapshot-based extract. No new
  responsibilities added.
- **OCP / LSP:** Public surface unchanged. Callers don't recompile against
  a new shape.
- **DIP:** `OSAllocatedUnfairLock` is a system primitive at the same level
  as the previous `NSLock` — same dependency direction.

## Out of scope

- Fixing the other Swift 6 warnings observed in the codebase
  (`AudioBufferConverter.swift`, `BLEPairingManager.swift`,
  `LiveTranscriber.swift`, `Localization.swift`, `MaskingPipeline.swift`,
  the App Intents enum types, `CognitoAuth.swift`). These need separate
  scoped PRs and are listed under "Deferred" in the PR body.
- Migrating any other file to `OSAllocatedUnfairLock`.
- Behavior changes to extraction, masking, or the dispatcher.

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/p1-4-fu && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build 2>&1 | tail -20`
   → BUILD SUCCEEDED.
2. `cd /Users/fsawadogo/aurion-lanes/p1-4-fu && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M5)' build 2>&1 | tail -20`
   → BUILD SUCCEEDED.
3. `xcodebuild test -only-testing:AurionTests/VideoRingBufferTests`
   → all 8 tests (7 original + 1 new) pass.
4. `xcodebuild ... build OTHER_SWIFT_FLAGS='$(inherited) -strict-concurrency=complete' 2>&1 | grep VideoRingBuffer`
   → returns only the compile-action line, no warnings.

## Security implications

- No PHI surface changed.
- No new logs or audit events.
- No new network calls.
- Privacy contract reaffirmed in comments at the lock-state boundary.
