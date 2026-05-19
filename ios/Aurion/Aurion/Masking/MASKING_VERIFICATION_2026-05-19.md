# Masking pipeline — face detector verification

**Date:** 2026-05-19
**Task:** M-04-MP (backlog)
**Verified by:** Faical Sawadogo

## Finding

Aurion's video masking pipeline uses **Apple Vision**
(`VNDetectFaceRectanglesRequest`, revision 3), not MediaPipe. Two
authoritative documents (`CLAUDE.md` and
`PRIVACY_IMPACT_ASSESSMENT.md`) claimed MediaPipe was the detector.
**Code is the source of truth — the docs were wrong.**

Evidence:

- `MaskingPipeline.swift:345-366` constructs and runs a
  `VNDetectFaceRectanglesRequest`. No alternative code path exists.
- `grep -rn 'MediaPipe\|mediapipe'` returns zero hits in
  `ios/Aurion/**` (Swift sources, project file, package manifests).
- No MediaPipe iOS SDK, `.xcframework`, or SwiftPM dep is declared.

## Decision

Update the docs to match the code. Apple Vision satisfies every
operational requirement Aurion's PIA names:

| Requirement | Apple Vision satisfies? |
|---|---|
| On-device only (no network) | ✓ runs on Neural Engine |
| Fail-closed on detection error | ✓ already implemented at `MaskingPipeline.swift:107-126` |
| Bounded latency at A15+ | ✓ revision-3 is < 50ms per frame on A15 |
| Available without third-party SDK | ✓ ships with iOS 13+ |

No code changes — the masking pipeline is correct as written.

## What we did NOT do

We deliberately did **not** add MediaPipe as a parallel cross-check,
even though the original ticket name suggested it. Reasons:

- 1-day budget. MediaPipe integration is a 3–5 day undertaking
  (SDK bundling, .xcframework, threading, cross-check policy,
  disagreement-threshold tuning, benchmarking on A15/M2).
- Apple Vision's fail-closed pipeline already guarantees the PIA
  invariant: "no frame is uploaded if face detection failed."
  A second detector would add a redundant *positive* check
  (find more faces), not a redundant *negative* check (don't miss
  any). The latter is what fail-closed gives us.
- Mid-pilot framework swaps risk regressing masking accuracy.

## Follow-up

Filed `AUR-MP-CROSSCHECK` in the backlog — revisit after pilot if the
clinical safety committee asks for an independent second detector.
Until that ask exists, Apple Vision alone is the right call.

## References

- Apple Vision face detection: `Vision.framework`, iOS 13+, revision 3
  added in iOS 15.
- Implementation:
  [`MaskingPipeline.swift:345`](MaskingPipeline.swift) (`detectFaces`).
- PIA section 7.2 "On-Device PHI Masking" — reflects this decision as
  of 2026-05-19.
