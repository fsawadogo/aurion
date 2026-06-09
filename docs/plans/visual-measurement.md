# In-Encounter Visual Measurement (Wound Size + ROM) — Design

**Issue:** #63 · **Status:** Post-MVP, design-only · **Area:** iOS / backend · **Differentiator**

> Turn "video enrichment" into a clinical instrument: **measure wound dimensions and range-of-motion angles from the encounter**, descriptively (measured, not interpreted), as a moat audio-only scribes (Abridge, Nuance DAX, Suki, Nabla, Ambience, Heidi) cannot cross. The hard part is not the UI — it is recovering metric **scale** from a frame.

---

## 0. The core problem

Turning a captured frame into a clinical number is a **scale-recovery problem, and scale is exactly what a 2D image does not contain.** Pixels become millimetres only with one of: dense metric **depth**, the camera's **intrinsic matrix + a known-size reference in frame**, or **multi-view geometry** with a known baseline.

Aurion's *primary* pilot wearable — Ray-Ban Meta via the Wearables Toolkit — gives **none** of these: monocular RGB, integration planned at `subscribeVideo(fps: 1)` (the "1080p · 60 fps" string in `MetaWearablesSource.swift` is aspirational UI copy, not the integration rate), no depth, no intrinsics guarantee, and the SDK is **stubbed pending Meta partner approval** (`start()` throws `notImplemented`). The glasses cannot recover absolute scale on their own. Full stop.

**The unlock:** the **iPhone already solves scale for free.** ARKit's visual-inertial world tracking yields metric world coordinates and exposes `ARFrame.camera.intrinsics` on every ARKit-capable device; LiDAR (Pro) adds dense metric depth. So we do **not** try to back geometry out of passive glasses frames in the cloud. We make the **iPhone an interactive, self-calibrating, physician-driven measurement instrument that runs entirely on-device** — which also happens to be the single safest regulatory framing available.

---

## 1. Scope

**In scope (per #63):**
- On-frame **wound measurement** (length / width; area as a Phase B increment).
- **ROM angle** estimation.
- **Descriptive output only** — measured, never interpreted.

**Out of scope (explicitly):**
- Wound **depth / undermining** — not reliable from this hardware.
- **Wound area on curved/contoured anatomy** (breast, scalp) — the planar-projection assumption breaks; planar wounds only.
- **Trends / serial deltas** ("area up 20% since last visit") — that is interpretation; forbidden in the MVP.
- **Glasses-based measurement** in v1 — deferred to Phase C, blocked on the Meta SDK, fiducial-mandatory, documentation-grade at best.
- Any **diagnosis, suggestion, or clinical conclusion** — Aurion's hard line.

**Non-goals the architecture must still respect:**
- The **descriptive-mode boundary** (CLAUDE.md): a measured number is a description; "consistent with…", "suggests…", "consider imaging" is interpretation and is forbidden.
- **No raw frames to the cloud, ever**; masking stays fail-closed before any upload; cloud vision providers stay **post-record-only** and never receive raw pixels; the append-only audit log; the provider-registry indirection.

---

## 2. Recommended approach (decisive)

**v1 = the iPhone interactive AR path. The Ray-Ban Meta passive/fiducial path is deferred and blocked on partner approval — do not gate v1 on it.**

**By capture device**
- **iPhone — the measurement instrument (ships):** ARKit world tracking + LiDAR depth (Pro) gives metric scale natively, no fiducial. The clinician places/adjusts measurement endpoints on screen; the app raycasts into the AR world and computes distance/angle in metric units, then asks for confirmation.
- **Ray-Ban Meta — documentation only (Phase C, blocked):** monocular, no depth, no intrinsics, SDK stubbed. The only viable metric path is a known-size printed **fiducial** (ArUco/AprilTag) in-frame, solved by homography, post-record, at low confidence. Treat glasses output as documentation-grade at best, fiducial-mandatory, behind a flag. Framing: *"the phone is the measuring camera; the glasses document."*

**By measurement kind**
- **Wound length / width (Phase A):** physician taps two endpoints in the AR view → raycast → metric distance. On LiDAR iPhones this is the strongest path: **~±2–5 mm, approaching clinical-grade** on a planar wound at close range with physician confirmation.
- **Wound area (Phase B):** assisted boundary segmentation projected onto the wound plane → planimetry. **Documentation-grade, planar wounds only.**
- **ROM angles (Phase A):** a **physician-aligned AR goniometer overlay** (clinician drags two lines onto the joint, app reports the angle) — honest, human-in-the-loop, sidesteps unreliable auto-pose. **~±5–10°, documentation-grade** (the same envelope as manual goniometry's inter-rater error — do not promise sub-5°). Auto-suggested 3D pose is a Phase B enhancement, still physician-confirmed.

**Grade, stated plainly:** LiDAR-iPhone wound length/width with physician confirmation is the closest thing to clinical-grade here. Everything else — wound area, all ROM, anything from the glasses — is **documentation-grade**, and the product must say so.

---

## 3. The technology stack (chosen, not a menu)

| Layer | Chosen tech (real API/framework) | Role | Device |
|---|---|---|---|
| **Scale (primary)** | `ARWorldTrackingConfiguration` + `ARFrame.sceneDepth`/`smoothedSceneDepth` (LiDAR) + `ARFrame.camera.intrinsics` | metric world coords for free; LiDAR adds dense depth | iPhone (LiDAR Pro best; world-tracking on all A15+) |
| **Scale (fallback / glasses)** | ArUco/AprilTag fiducial of known size + homography; or `AVCaptureConnection.isCameraIntrinsicMatrixDeliveryEnabled` for a non-AR iPhone path | pixel→mm where ARKit unavailable; only metric path for monocular glasses | glasses (Phase C), non-AR iPhone |
| **Wound boundary** | `VNGenerateForegroundInstanceMaskRequest` (iOS 17+, **run-once then query a point** — not interactive refinement) with a physician-traced polygon fallback on iOS 16 | assisted wound outline for area | iPhone |
| **Distance / area math** | SceneKit / `simd` raycast + planar projection + shoelace | endpoint distance, planimetry | iPhone |
| **ROM / pose** | `VNDetectHumanBodyPoseRequest` (iOS 14+, 2D), `VNDetectHumanHandPoseRequest` (hand ROM), `VNHumanBodyPose3DObservation` (iOS 17+, A15+, 3D) — all physician-confirmed | auto-suggest joint angles (Phase B) | iPhone |
| **Interactive UI** | RealityKit `ARView` + SwiftUI overlay; `ARRaycastQuery` to place/drag endpoints; AR goniometer overlay for ROM | physician places/adjusts/confirms — the ground-truth gate | iPhone |
| **On-device vs cloud** | **100% on-device geometry** — zero raw pixels to cloud; only structured numbers + a masked thumbnail leave | privacy + descriptive integrity | iPhone |
| **Masking** | existing `MaskingPipeline` (Vision face blur + OCR redaction), fail-closed before upload | measurement reads the in-memory raw/AR frame; masking only blurs faces/screen, never the wound/limb geometry | iPhone |
| **Schema** | new `MeasurementCitation` + `source_type:"measurement"` on `NoteClaim` | carry numbers + provenance into the note | backend + iOS |
| **Config** | AWS AppConfig flags: `measurement_enabled`, `measurement_methods_allowed`, `measurement_min_confidence`, device gating | per-pilot tuning, no rebuild | backend |
| **Audit** | DynamoDB append-only: `MEASUREMENT_GENERATED / REVIEWED / EDITED / SUPPRESSED` | full provenance | backend |

**Deliberately NOT chosen for v1:** MediaPipe BlazePose, MobileSAM, Depth Anything v2 / Apple Depth Pro. Monocular ML depth is **relative, not metric** — it needs the same calibration you'd rather get from ARKit — and these add 40–500 MB, 100–2000 ms latency, and a validation burden. Apple-native ARKit + Vision gives metric scale and pose without shipping a third-party model. Revisit only if the glasses path forces it.

---

## 4. How it fits Aurion's architecture

**Measurement-citation schema** (extends the existing claim/citation pattern — no breaking change to Stage 1 / Stage 2):

```jsonc
// NoteClaim gains source_type: "measurement"
{
  "id": "claim_042",
  "text": "Wound length measured at approximately 42 mm (iPhone AR, LiDAR, physician-confirmed).",
  "source_type": "measurement", "source_id": "meas_001"
}
// New MeasurementCitation
{
  "measurement_id": "meas_001", "session_id": "uuid", "frame_id": "frame_00214",
  "kind": "wound_length",            // wound_length | wound_width | wound_area | rom_angle
  "value": 42.0, "unit": "mm",       // mm | cm2 | deg
  "method": "arkit_lidar",           // arkit_lidar | arkit_world | fiducial_homography | vision_pose_3d | ar_goniometer
  "confidence": "high", "confidence_reason": "stable tracking, perpendicular view, planar surface",
  "scale_source": "lidar_depth", "masking_status": "confirmed",
  "physician_confirmed": true, "provider_used": "on_device", "model_version": "meas-1.0",
  "certified_measurement": false     // ALWAYS false — the disclaimer is structural, not cosmetic
}
```

- **Note-section injection:** measurements route as claims into `wound_assessment` (plastic), `physical_exam` / `functional_assessment` (orthopedic / MSK) — sections the templates already define. Add an optional `measurement_output_expected` flag to `TemplateSection` so the pipeline knows a section can carry metrics.
- **NoteReview confirm-UX:** mirrors today's tap-to-source. A measurement does **not** enter the note until the physician **confirms / edits / rejects** (allow edit — surgeons will want to nudge an endpoint — and audit original vs edited). The review card shows the masked frame with the overlay, value, method, and confidence.
- **On-device, not backend:** measurement is computed on the phone; the backend only receives the structured `MeasurementCitation` (numbers + provenance) and a masked thumbnail. **Do not** build a cloud-side "validate the measurement against the frame" step — it would require re-downloading masked frames and buys nothing. Measurement validation is on-device or it doesn't happen.
- **AppConfig** gates the feature, allowed methods, and the confidence floor; likely gate the high-confidence wound path to LiDAR devices.

**Descriptive-mode boundary — correct vs incorrect output:**
- ✅ "Wound length measured at approximately 42 mm; width approximately 18 mm (iPhone AR, physician-confirmed)."
- ✅ "Right shoulder external rotation measured at approximately 35 degrees (AR goniometer, physician-aligned)."
- ❌ "Wound area up 20% since last visit, suggesting delayed healing." (trend + interpretation)
- ❌ "35° ROM is consistent with adhesive capsulitis; consider imaging." (diagnosis + recommendation)

---

## 5. Accuracy & honesty budget

| Path | Realistic precision | Grade |
|---|---|---|
| iPhone Pro LiDAR + AR + physician-confirmed, planar wound L/W | ~±2–5 mm | Near clinical-grade |
| iPhone non-LiDAR (A15 world-tracking) L/W | ~±5–10 mm | Documentation-grade |
| Wound area (planar only) | method-dependent; flag as estimate | Documentation-grade |
| ROM (AR goniometer or 3D pose, physician-confirmed) | ~±5–10° (≈ manual goniometry) | Documentation-grade |
| Glasses monocular + fiducial (Phase C) | ~±5–15% | Documentation-grade, low confidence |

**Refusal bar — below this, emit `status:"not_measurable"` with a reason, never a number:** no scale lock (tracking unstable / no depth confidence), viewing angle past an obliquity threshold, low pose/segmentation confidence, non-planar surface for area, or masking failure on the source frame. **Every emitted number carries "approximately," its `method`, and a `confidence`.** No automatic serial/trend math. The confidence threshold must be **clinically validated, not assumed** — a guessed 0.6 cutoff is not defensible.

---

## 6. Regulatory / privacy posture

- **SaMD line:** producing numeric clinical measurements drifts toward "measuring device." Stay a **documentation aid** via four non-negotiables: (1) **no accuracy claims** anywhere — UI, marketing, pilot docs shared with regulators; (2) an **"approximate — not a certified measurement"** disclaimer on every measurement and in every export; (3) **mandatory physician confirm/edit/reject** before a number enters the note; (4) **descriptive only** — no trends, interpretation, or diagnosis. Manual goniometers/rulers are themselves largely non-device; mirroring that "physician-placed measurement aid" framing is the escape route.
- **Law 25 / PIPEDA:** a measurement joined to a session is **derived PHI** — same KMS encryption, retention, audit, and erasure rules as notes (confirm the purge logic covers `MeasurementCitation`). On-device-only computation keeps raw frames from transiting, preserving the moat.
- **Go/no-go gates before a real patient:** (a) an **accuracy characterization study** (AR vs manual ruler/goniometer, blinded, N≥30) — even if you never publish a claim, you must know your real error envelope to set the refusal bar; (b) **legal review of export labeling**; (c) **informed consent + clinician acknowledgment** that measurements are approximate aids; (d) Law-25 purge/audit verified for measurement data; (e) a **Health Canada / FDA pre-submission (Q-Sub)** — not blocking the research pilot, but decide now if commercialization is on the roadmap, because it shapes what you may claim later.

---

## 7. Phased plan

**Phase A — smallest shippable slice, ships on iPhone today, zero Meta dependency:**
- `MeasurementCitation` schema + `source_type:"measurement"` + AppConfig flags + audit events.
- iPhone interactive **AR wound length/width** (ARKit tap-to-place endpoints, raycast metric distance, LiDAR + world-tracking fallback).
- **AR goniometer ROM** (physician-aligned overlay).
- NoteReview confirm card + disclaimer labeling + descriptive-only strings.

**Phase B — increments on iPhone:**
- Assisted wound segmentation (`VNGenerateForegroundInstanceMaskRequest`, iOS 17+) → **wound area** planimetry (planar only).
- Auto-suggested ROM via `VNHumanBodyPose3DObservation` (physician-confirmed).
- Run the accuracy characterization study in parallel.

**Phase C — BLOCKED on Meta SDK partner approval:**
- Glasses passive **fiducial-based** wound measurement, post-record, low confidence, fiducial-mandatory, behind a flag + confidence floor.

**Blocked on Meta SDK:** anything measuring from glasses frames. **Ships on iPhone now:** everything in A and B — the iPhone is the instrument.

---

## 8. Decisions to confirm before building

1. **Do Perry and Marie actually want numbers?** Confirm Perry's wound standard (length×width? area? PUSH/BWAT?) and Marie's joints/planes (AAOS goniometry). **The riskiest assumption in the whole feature** is that clinicians want metric output at all rather than descriptive ranges.
2. **Accuracy-claim posture:** commit to **no accuracy claims + documentation-aid labeling** for the pilot, and decide whether to file a Health Canada / FDA pre-sub now (only if commercialization is planned).
3. **ROM approach:** physician-aligned **AR goniometer** (recommended — defensible, human-in-loop) vs auto 3D pose (flashier, less reliable).
4. **Device gating:** likely gate the high-confidence wound path to **LiDAR iPhones**; decide whether non-LiDAR A15 measurement ships at lower confidence or is suppressed.
5. **Refusal threshold:** the confidence floor below which the app emits "not measurable" — must come from the validation study, not a guess.

**Riskiest assumptions:** that clinicians want measurements; that ARKit world-tracking on non-LiDAR A15 is accurate enough (may force LiDAR-only gating); that wounds are planar enough for area (curved anatomy breaks it); and that the Meta SDK lands in a timeframe that matters (treat it as indefinitely blocked and ship the iPhone path regardless).

---

## 9. Relevant files (when Phase A starts)

- `ios/Aurion/Aurion/Capture/BuiltInCaptureSource.swift` — add the ARKit measurement path.
- `ios/Aurion/Aurion/Capture/MetaWearablesSource.swift` — Phase C, blocked.
- `ios/Aurion/Aurion/Masking/MaskingPipeline.swift` — unchanged ordering; measurement reads the in-memory raw frame.
- `backend/app/core/types.py` + `models.py` — new `MeasurementCitation` + `source_type:"measurement"`.
- NoteReview UI — the confirm card (confirm/edit/reject, tap-to-source).
- `backend/app/core/audit_events.py` — `MEASUREMENT_*` events + kwargs whitelists.

---

*This design was produced by a multi-perspective analysis (capture-geometry, on-device CV/ML, clinical validity, regulatory/SaMD, competitive SOTA, architecture-fit) with adversarial verification of its load-bearing technical claims. Implementation is deferred pending the §8 decisions; Phases A–B ship on iPhone with no Meta dependency.*
