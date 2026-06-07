# Plan — bug-281

## Task
#281 — `CaptureManager` appends mic PCM to the uploaded recording **unconditionally**, so audio keeps recording while the session is PAUSED (privacy defect) and pre-start / post-stop buffers can leak into the WAV.

## Why
In `handleAudioSampleBuffer` the `isCapturing && !isPaused` guard protects only the `audioLevel` meter (inside a `@MainActor` Task); the PCM `append` runs unconditionally on the nonisolated audio thread. `pauseCapture` sets `isPaused = true` but the comment ("samples are ignored") is false for audio — bytes keep accumulating. For a consent-driven clinical recorder, pause exists precisely so sensitive moments are NOT captured. (The video path is already correctly gated — `capturedFrames.append` sits inside the MainActor guard.)

## Approach
Extract a small thread-safe `AudioCaptureBuffer` (NSLock + `Data` + `active` flag) as the single sync point between the audio thread (append) and the main actor (start/pause/resume/stop). `append` is a no-op unless active, so paused intervals and pre-start/post-stop buffers never reach the WAV. This also centralizes the lock bookkeeping currently scattered across 7 sites (DRY) and is fully unit-testable (no AVFoundation deps). Keep the append OFF the main actor (audio buffers are frequent — hopping each to MainActor would risk backpressure/glitches).

Lifecycle wiring in `CaptureManager`:
- `startCapture` reset → `audioBuffer.reset()`; after `captureSession.startRunning()` → `audioBuffer.activate()`.
- `stopCapture` after `stopRunning()` → `audioBuffer.deactivate()` (keeps data for `getRecordedAudioData`).
- `pauseCapture` → `deactivate()`; `resumeCapture` → `activate()`.
- Reads (`getRecordedAudioData`, `getRecordedPCMBuffer`) → `snapshot()`; `getRecordedAudioByteCount` → `byteCount`; `discardRecordedAudio` → `reset()`; append → `audioBuffer.append(result.pcm)`.

Files: new `ios/Aurion/Aurion/Capture/AudioCaptureBuffer.swift`, `Capture/CaptureManager.swift`, new `AurionTests/AudioCaptureBufferTests.swift`.

## Acceptance criteria
- [ ] AC-1: appending before `activate()` is dropped (`byteCount == 0`) — pre-start buffers don't leak — `AudioCaptureBufferTests.dropsBeforeActivate`.
- [ ] AC-2: after `activate()`, appends accumulate — `...accumulatesWhenActive`.
- [ ] AC-3: after `deactivate()` (pause), appends are a no-op — **the fix** — `...pauseStopsAppending`.
- [ ] AC-4: `activate()` again (resume) re-enables appends, preserving prior bytes — `...resumeContinues`.
- [ ] AC-5: `reset()` clears bytes and deactivates — `...resetClears`.
- [ ] AC-6: app builds iPhone 17 + iPad Pro 11" (M4) — CI.

## DRY / SOLID check
- **Existing helpers to reuse**: `WAVBuilder.build` and the audio-format constants are untouched; the new buffer wraps the existing `NSLock`+`Data` pattern that was duplicated at 7 call sites.
- **New helper introduced?**: `AudioCaptureBuffer` — justified: it's the 7th copy of lock/unlock-around-`audioPCMData` (well past the extract threshold) AND crosses the audio-thread/main-actor boundary that the bug lived in. SRP: one type owns PCM accumulation + the capture gate.
- **iOS UI only — mobile-ios-design**: n/a (no UI).

## Out of scope
- Auditing `capturedDuration` vs the record window in `audio_upload_started`/`_succeeded` (the issue's secondary ask) — touches `AudioUploadCoordinator`/audit; deferred to a follow-up so this PR stays a focused, low-risk capture fix.
- The clip ring buffer's intentionally-ungated append (cleared on stop; documented at the call site).

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -destination 'iPhone 17' -only-testing:AurionTests/AudioCaptureBufferTests` → green.
2. CI build matrix.

## Security implications
PRIVACY-positive: this is the fix — paused audio no longer reaches the uploaded WAV, honoring the consent/pause contract. No PHI logged (no new logging). No audit/secret/AI path. Raw audio handling stays in-memory with the same lock discipline, now centralized.
