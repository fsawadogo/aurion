# P1-5-FU: dedicated `xcodebuild test` step for codec-sensitive clip tests (iOS lane)

**Parent plan:** P1-5 (`docs/plans/p1-5-clip-masking.md`) shipped the
`MaskingPipeline.maskClip` happy-path test behind the `AURION_RUN_CLIP_HAPPY_PATH=1`
env var because the iOS Simulator's H.264 codec allocator (Fig err=-12900 /
`kCMSampleBufferError_AllocationFailed`) exhausts its slot pool when the
happy-path runs alongside other AV-heavy tests in the same `xcodebuild test`
invocation. The standalone single-target run (`-only-testing:`) succeeds every
time; only full-suite runs flake.

**Backlog item:** P1-5-FU — CI codec exhaustion fix for clip tests.

## Why

The gated test (`ClipDispatcherTests.swift:254`,
`@Test(... .disabled(if: ProcessInfo.processInfo.environment["AURION_RUN_CLIP_HAPPY_PATH"] != "1"))`)
is currently dead code in CI — no workflow sets the env var, so the test is
always skipped. We need an isolated `xcodebuild test` step that opts in via the
env var and runs JUST that test, in its own simulator boot, so the codec slot
pool isn't pre-exhausted by the rest of the suite.

Per CLAUDE.md §"Privacy" and the dual-mode privacy contract: this PR does not
touch product code. The fail-closed `maskClip` guarantee is unchanged. The
clip-pipeline test surface we're un-gating in CI ALREADY asserts:

- `result.success == true` only when fail-closed conditions are absent
- the masked output is a real, audio-free MP4 (`audioTracks.isEmpty == true`)
- `framesFailed == 0` on the happy path

Putting CI behind that assertion strengthens the masking proof, not weakens it.

## Approach

`ios-testflight.yml` is today's PR-time iOS workflow. Its `build` job runs on
every PR touching `ios/**` (`push: main` and `pull_request: main` triggers,
paths-filtered to `ios/**`). It only does `xcodebuild build` — no tests. We
extend `build` with two test steps:

1. **Main test step** — `xcodebuild test -scheme Aurion -only-testing:AurionTests`.
   The gated test SKIPS here because `AURION_RUN_CLIP_HAPPY_PATH` is not set,
   so the codec exhaustion never trips. This is the primary signal — fails
   block the PR.
2. **Codec-isolated step** — same `xcodebuild test` but with
   `-only-testing:AurionTests/MaskClipTests/happyPath_producesAudioFreeMP4WithFrames`
   and `AURION_RUN_CLIP_HAPPY_PATH=1` exported in the step `env:`. Runs AFTER
   step 1 so the main signal is observable first. `continue-on-error: true`
   so a simulator codec flake doesn't block the PR — the main suite remains
   the gate.

Shared `xcodebuild` invariants (project dir, scheme, destination, Xcode
version selection) factor into the workflow-level `env:` block and the
existing `Select Xcode` step. No duplicated arg lists (DRY §6c).

## Acceptance criteria

- [ ] AC-1: `.github/workflows/ios-testflight.yml` validates as YAML
  (`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ios-testflight.yml'))"` exits 0).
- [ ] AC-2: A new step "Run AurionTests" runs `xcodebuild test` against the
  same iPhone 17 simulator as the existing build step, with
  `-only-testing:AurionTests`. The gated test reports as `skipped` here,
  not `failed` — confirming the env-var gate is real.
- [ ] AC-3: A new step "Run codec-exhaustion-sensitive tests (isolated)"
  runs `xcodebuild test -only-testing:AurionTests/MaskClipTests/happyPath_producesAudioFreeMP4WithFrames`
  with `AURION_RUN_CLIP_HAPPY_PATH=1` exported in the step `env:`, sits
  AFTER the main test step, and carries `continue-on-error: true`.
- [ ] AC-4: Verified locally — invoking the isolated command on a clean
  simulator returns `TEST SUCCEEDED` for the gated test. (The OS-version
  / simulator availability in the local sandbox may differ from
  `macos-26`; documented in the PR body.)
- [ ] AC-5: `docs/dev/ios-tests.md` documents why the test is gated and how
  to opt in locally, with the exact command.

## DRY / SOLID check

- **Existing helpers to reuse:**
  - Workflow-level `env: IOS_PROJECT_DIR / IOS_SCHEME` already exists at
    `.github/workflows/ios-testflight.yml:32-34` — both test steps reference
    these via `${{ env.IOS_SCHEME }}` instead of repeating literals.
  - The `Select Xcode (newest installed)` step at line 42 sets up xcodebuild
    for the whole `build` job — both test steps inherit it. We do NOT
    duplicate that selection logic.
  - The simulator destination string is identical to the existing
    `Build for iPhone 17 Simulator` step; promoted to a job-scoped
    `SIM_DESTINATION` env var so all three steps (build, test main,
    test isolated) reference the same value.
- **New helper introduced?:** No. One workflow-level env var (`SIM_DESTINATION`)
  promoted to remove three copies of the same destination string. That's the
  third occurrence — DRY rule from §6c is satisfied.
- **SRP:** The new isolated step does ONE thing — run the codec-sensitive
  test target in isolation. No lint, no coverage, no PR comments tacked on.
- **OCP / LSP / ISP / DIP:** Workflow change, no code interfaces touched.
- **iOS UI tasks only — `mobile-ios-design` consulted:** N/A — CI workflow
  change, no UI surface.

## Out of scope

- Fixing the underlying codec exhaustion in `MaskingPipeline.maskClip` (e.g.
  adding `autoreleasepool` around the per-frame loop or explicit `finishWriting`
  + `nil`-ing of the writer reference). The task description allows this as an
  optional secondary commit if the fix is clearly correct from reading the
  code; reviewed — the current implementation already calls
  `await writerInput.markAsFinished()` and `await writer.finishWriting()` in
  the success path AND in every failure path. The slot exhaustion is
  process-scoped to the simulator's parallel-clone test runner, not a leak
  inside `maskClip`. No code change qualifies as "clearly correct" — deferred.
- Adding the gated test to the TestFlight upload path (it runs on PR-time
  only, not on every TestFlight dispatch). The TestFlight `testflight` job
  is unchanged.
- Splitting `ios-testflight.yml` into separate `ios-test.yml` and
  `ios-testflight.yml` files. The existing layout (one workflow, two jobs)
  works; reshuffling is a bigger surgery deferred to a separate PR.

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/p1-5-fu && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ios-testflight.yml'))"`
   → exits 0, no error.
2. `cd /Users/fsawadogo/aurion-lanes/p1-5-fu/ios/Aurion && xcodebuild test -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:AurionTests/MaskClipTests 2>&1 | tail -25`
   → reports `happyPath_producesAudioFreeMP4WithFrames` as `skipped`
   (proves the gate is real today, before the isolated step turns it on).
3. `cd /Users/fsawadogo/aurion-lanes/p1-5-fu/ios/Aurion && AURION_RUN_CLIP_HAPPY_PATH=1 xcodebuild test -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:AurionTests/MaskClipTests/happyPath_producesAudioFreeMP4WithFrames 2>&1 | tail -15`
   → `TEST SUCCEEDED` (proves the isolated step's command works in
   practice).

## Security implications

- No PHI surface changed.
- No new audit events.
- No new network calls.
- Fail-closed masking guarantee (P0-01) preserved — the gated test asserts
  `audioTracks.isEmpty == true` on the masked output and `framesFailed == 0`,
  which is strictly stronger than skipping the test. Wiring CI to actually run
  it (in isolation) hardens the privacy contract verification, not weakens it.
- No new secrets, no new IAM roles, no new MCP surfaces.
