# iOS test guide

## Running the test suite locally

```bash
cd ios/Aurion
xcodebuild test \
    -scheme Aurion \
    -destination 'platform=iOS Simulator,name=iPhone 17' \
    -only-testing:AurionTests
```

This is the same invocation CI runs in the "Run AurionTests" step of
`.github/workflows/ios-testflight.yml`. Pass or fail here is the
authoritative iOS test signal for PRs.

## Codec-sensitive tests (opt-in)

`MaskClipTests/happyPath_producesAudioFreeMP4WithFrames` exercises the
real H.264 encode path inside `MaskingPipeline.maskClip` — it builds a
synthetic clip, runs the full Vision face-detect + AVAssetWriter
pipeline, and asserts the output MP4 has a video track and zero audio
tracks (the dual-mode privacy contract).

Running this test ALONGSIDE other AV-heavy tests in the same
`xcodebuild test` invocation reliably exhausts the iOS Simulator's
process-scoped H.264 codec slot pool (`Fig err=-12900` /
`kCMSampleBufferError_AllocationFailed`). The test is therefore gated
behind `AURION_RUN_CLIP_HAPPY_PATH=1` via Swift Testing's
`.disabled(if:)` so the broad suite skips it without flakiness.

To opt in locally:

```bash
cd ios/Aurion
TEST_RUNNER_AURION_RUN_CLIP_HAPPY_PATH=1 \
xcodebuild test \
    -scheme Aurion \
    -destination 'platform=iOS Simulator,name=iPhone 17' \
    -only-testing:AurionTests/MaskClipTests
```

Notes:

- Use the `TEST_RUNNER_` prefix on the env var name — `xcodebuild`
  forwards `TEST_RUNNER_<VAR>` into the simulator's test runner
  process. A bare `AURION_RUN_CLIP_HAPPY_PATH=1` prefix only sets the
  variable on the `xcodebuild` parent process and the test is reported
  as `skipped`. See `man xcodebuild`, "Environment Variables" section.
- Swift Testing does NOT support method-level `-only-testing:` paths
  (a method-level filter matches zero tests and produces a vacuous
  `TEST SUCCEEDED`). Use the struct-level filter
  `AurionTests/MaskClipTests`. The other test in the struct
  (`mask_polymorphicEntry_routesClipToMaskClip_andFailsClosed`) is a
  ~0.1 s fail-closed smoke that does NOT exercise the codec, so
  running it alongside is harmless.
- Even with the isolated invocation, the codec exhaustion can still
  show up if the simulator is in a stale state from a prior `xcodebuild
  test` run in the same shell session. If you hit it, fully reset:

  ```bash
  xcrun simctl shutdown all
  xcrun simctl erase 'iPhone 17'
  ```

## CI behavior

`.github/workflows/ios-testflight.yml` runs both invocations on every PR
that touches `ios/**`:

1. **Run AurionTests** — the broad suite, codec-sensitive test skipped.
   Pass/fail is the PR gate.
2. **Run codec-exhaustion-sensitive tests (isolated)** — runs the gated
   test in its own xcodebuild invocation (fresh simulator, fresh codec
   pool). Carries `continue-on-error: true` so a simulator codec flake
   here cannot block the PR — the main suite remains the source of
   truth. The step runs with `if: always()` so we get the signal even
   when step 1 fails.

## References

- P1-5 (PR #205) — landed `MaskingPipeline.maskClip` and the gate
- P1-5-FU (this PR) — wired the gated test into CI as an isolated step
- `ios/Aurion/AurionTests/ClipDispatcherTests.swift:229` —
  `MaskClipTests` struct + the gate
- `.github/workflows/ios-testflight.yml` — the workflow that drives both
  steps on PR-time
