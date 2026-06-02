# P1-4: VideoRingBuffer + VisualEvidence enum (iOS lane)

## Source plan

This PR implements step **P1-4** of the dual-mode visual evidence plan.

- Master plan: `/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`
- Phase: 1 (infrastructure, zero behavior change)
- Default AppConfig mode stays `frames_only` after this PR ships, so no
  existing call site changes behavior.

## What this PR delivers

iOS-only, additive, zero behavior change. The PR lays the foundation that
P1-5 (dispatcher) and P1-6 (reviewer) will build on, but on its own it
does NOT change the visual evidence pipeline:

1. **`Capture/VideoRingBuffer.swift`** (new) — thread-safe deque of
   `CMSampleBuffer` references, capped at `clip_ring_buffer_seconds ×
   videoCaptureFPS` items. Exposes `append`, `clear`, and
   `extract(around:duration:)` which encodes a window to a temp `.mp4`
   via `AVAssetWriter` (H.264 main profile, **no audio track**).

2. **`Session/VisualEvidence.swift`** (new) — polymorphic enum that
   wraps either the existing `CapturedFrame` or a clip URL. The frame
   case is byte-identical to today's pipeline; the clip case is unused
   in P1-4 and consumed by P1-5.

3. **`Capture/CaptureManager.swift`** (additive) — the existing frame
   extractor runs unchanged; AFTER it runs we also push the raw sample
   buffer into the ring buffer. On stop / reset, the ring buffer is
   cleared. **No dispatcher logic, no uploads, no behavior change.**

4. **`AurionTests/VideoRingBufferTests.swift`** (new) — covers
   `append` + overflow, `extract` success + failure, `clear`, thread
   safety under TaskGroup-driven parallel appends, and proves the
   extracted MP4 has no audio track.

## Acceptance criteria

- [ ] **AC-1**: VideoRingBuffer appends sample buffers up to its cap;
  oldest are evicted on overflow. Verified by
  `VideoRingBufferTests.append_evictsOldestOnOverflow`.
- [ ] **AC-2**: `extract(around:duration:)` returns a valid MP4 URL
  whose `AVURLAsset` reports an empty `.audio` track list. Verified by
  `VideoRingBufferTests.extract_returnsAudioFreeMP4`.
- [ ] **AC-3**: `extract(around:duration:)` throws a typed error when
  the ring is empty or the window has no samples. Verified by
  `VideoRingBufferTests.extract_throwsOnEmptyRing`.
- [ ] **AC-4**: `clear()` empties the deque. Verified by
  `VideoRingBufferTests.clear_emptiesDeque`.
- [ ] **AC-5**: Parallel `append` from a TaskGroup does not crash and
  the final count is bounded by the cap. Verified by
  `VideoRingBufferTests.append_threadSafeUnderTaskGroup`.
- [ ] **AC-6**: `xcodebuild` on iPhone 16 Pro and iPad Pro 11-inch (M4)
  both succeed.
- [ ] **AC-7**: Existing `AurionTests` continue to pass — no regression
  in the frame pipeline or masking tests.

## DRY / SOLID check

- **Existing helpers reused**: `CapturedFrame` from CaptureManager,
  `videoCaptureFPS` from CaptureManager, the existing
  `videoProcessingQueue` delegate path.
- **New helper introduced**: `VideoRingBuffer`. This is a NEW abstraction,
  but it's a clear boundary — the ring is a distinct responsibility from
  the per-frame JPEG extractor that lives on `CaptureManager`. Single
  Responsibility Principle: ring buffer owns the rolling window + MP4
  encode; CaptureManager owns the AVCaptureSession lifecycle.
- **Liskov**: `VisualEvidence.frame` carries the same `CapturedFrame`
  type the existing pipeline already uses, so every downstream call
  site that switches on the enum can keep using the same frame data.
- **Open/Closed**: The ring buffer is additive — no existing call site
  changes behavior. The clip path is unused in P1-4 and the frame
  pipeline runs first and unchanged.
- **iOS UI consulted (`mobile-ios-design`)**: n/a — this PR has no UI
  surface.

## Security implications

- **Raw frames never leave iOS unmasked**: The ring buffer holds RAW
  (unmasked) `CMSampleBuffer` references in MEMORY ONLY. It never
  uploads or persists to disk during normal capture. P1-5 will run the
  masking pipeline on the extracted MP4 BEFORE upload. A comment on
  `VideoRingBuffer` makes this contract explicit so future readers
  don't accidentally upload raw bytes.
- **No PHI in logs**: The ring buffer logs counts only, never frame
  content.
- **iOS Keychain**: Not touched — voice embedding is the only thing
  that lives there and this PR doesn't go near it.
- **Fail-closed**: `extract` throws rather than returning partial data
  when the ring can't cover the requested window. P1-5 callers must
  handle the throw before upload.

## Out of scope

- Dispatcher logic that chooses frame vs clip per trigger (P1-5).
- Masking the clip (P1-5 — runs `AVAssetReader` → per-frame masking →
  `AVAssetWriter` writes a new audio-free MP4).
- Upload to backend (P1-5 wires `APIClient.uploadClip`).
- Reviewer UI for clips (P1-6).
- AppConfig wiring for `visual_evidence_mode`, `clip_window_ms`, or
  `clip_ring_buffer_seconds` — backend `ClientPipelineResponse` doesn't
  expose them yet (lands with P1-1 backend slice). P1-4 hardcodes
  sensible defaults with a comment.
