# Plan — doctor-stage2-gate

## Task

Make imported doctor sessions wait for visual Stage 2 before they can be signed, and ensure the doctor pipeline honors the admin-selected vision provider.

## Durable product direction

- **Do not make iOS changes in this workstream.** We own the shared backend/web pipeline and keep its API compatible with the app. If evaluation proves an iOS adjustment is needed, Faical will implement that client change.
- The target is trustworthy physician output that integrates audio and video into **grounded clinical interpretation**, comparable in usefulness to Marie's reference output.
- Interpretation must not be a literal list of scene descriptions. It may synthesize an assessment from captured findings only when every clinical conclusion is supported by cited audio/video evidence.
- Grounded Lab is a diagnostic tool, not the measured product path. Acceptance is based on the real doctor pipeline.

## Why

The `15 min knee pain visit` evaluation could not measure multimodal note quality. Its doctor-pipeline Stage 2 ran before extracted frames existed, returned `no_visual_evidence`, and the note was finalized as audio-only. The later Grounded Lab run saw the frames, but it was not the doctor pipeline and used different provider routing.

The provider configuration page selects Gemini for vision and Anthropic for note generation. The doctor Stage 2 path previously bypassed the admin vision override when resolving frame captions, so runtime behavior could disagree with the admin configuration.

This task repairs those measurement blockers. It deliberately does not claim that the current synthesis already matches Marie's output; that is measured after deployment with the five original clips.

## Approach

- `backend/app/api/v1/video_import.py`: run Stage 2 only after frame extraction and masking have completed; keep the import job in progress until Stage 2 reaches a terminal result.
- `backend/app/api/v1/notes.py`: fail closed on final approval while Stage 2 is absent, pending, or running. Permit an audio-only sign-off after a terminal Stage 2 failure only through an explicit physician override.
- `backend/app/modules/config/provider_registry.py`: make frame-aware Stage 2 resolution honor the audited admin runtime vision override.
- Web import and note review: do not redirect or enable final approval while visual enrichment is in flight; expose an explicit audio-only approval action after failure.
- Add focused backend and web regression coverage.

## Acceptance criteria

- [x] AC-1: A doctor video import invokes Stage 2 only after frame extraction/masking and does not complete the import job before Stage 2 terminates.
- [x] AC-2: Final approval is rejected when no Stage 2 job exists or when Stage 2 is pending/running.
- [x] AC-3: A terminal Stage 2 failure remains reviewable but requires an explicit `allow_stage2_failure` acknowledgement to sign audio-only.
- [x] AC-4: Frame-aware doctor Stage 2 uses the admin runtime vision override (Gemini in the current admin configuration).
- [x] AC-5: The web import page waits for job completion, and note review disables ordinary approval while Stage 2 is active.
- [x] AC-6: Focused backend and web regressions pass; the full backend unit suite passes.
- [x] AC-7: `git diff main...HEAD -- ios/` is empty.
- [ ] AC-8: After deployment, rerun the five original `15 min knee pain visit` clips through the doctor pipeline and compare the produced claims, evidence, assessment, and plan with Marie's reference.

## Test plan (executable)

1. Focused backend Stage 2, approval, import, and provider tests — 53 passed.
2. Full backend unit suite — 2,219 passed, 1 skipped (2,215 in the standard run; four temp-path-sensitive tests rerun with a workspace basetemp and passed).
3. Ruff on changed backend and test files — all checks passed.
4. Focused web import/review tests — 25 passed.
5. ESLint on changed production web files — passed.
6. `git diff --name-only main...HEAD -- ios/` — empty.
7. After merge/deploy: import the five original clips through the clinician upload flow, monitor the real Stage 1/Stage 2 jobs in CloudWatch, and score the note against Marie's reference.

## Known verification limitation

Repository-wide web `tsc --noEmit` still reports pre-existing errors in unrelated AI Prompts, Audit, and VideoImport test fixtures. No changed production TypeScript file introduced a type error, and the focused web suites pass.

## Security implications

- No new AI prompt is introduced. Existing grounded-synthesis and citation rules remain intact.
- No direct model SDK call is added; provider selection remains behind the provider registry.
- No PHI is added to logs, errors, configuration, or audit fields.
- Existing frame masking proof remains a prerequisite to visual processing.
- Approval becomes stricter: a physician cannot unknowingly sign before visual processing finishes.
- Explicit audio-only approval after terminal failure is visible and intentional rather than silent.

## Out of scope

- iOS implementation. If a client change becomes necessary, document the backend contract and hand the iOS work to Faical.
- Grounded Lab behavior or UI.
- Claiming Marie-level interpretive quality before the real doctor-pipeline rerun is measured.
- Ungrounded diagnosis, uncited inference, or fabrication.
- Temporal video/clip reasoning changes beyond making the existing Stage 2 run at the correct time.

## Follow-up measurement

The next loop uses the real doctor pipeline, the five original clips (never the merged `CORRECT` video), and Marie's commented answer key. It separates:

1. capture/coverage failures,
2. vision understanding failures,
3. audio-video fusion failures,
4. grounded clinical synthesis failures, and
5. presentation/usability gaps for the physician.

Only then should synthesis prompts or evidence-merging logic be changed.
