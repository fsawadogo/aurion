# Plan — VID-04 (compliance-critical)

## Task
VID-04 — Real server-side frame masking (face detect + blur, fail-closed) +
S3 store + `SERVER_MASKING_*` audit. Swaps the VID-03 stub.

## Why
Stage C of the design — the trust-boundary change: unmasked patient faces exist
transiently inside the backend; the server becomes the masking authority. The
CODE ships DARK behind `feature_flags.video_import_enabled` (still default
False). **Enabling the flag in any env with real PHI requires compliance
sign-off** — merging the dark code does not.

## Approach
- **Detection: local, in-process.** Use OpenCV's bundled Haar cascade
  (`cv2.data.haarcascades/haarcascade_frontalface_default.xml`) — ships with
  `opencv-python-headless`, so **no model binary is vendored**. Unmasked frames
  never leave the task (no managed CV API). Pragmatic for a fail-closed pilot;
  the `mask_frame` signature lets a stronger detector (DNN/MediaPipe) drop in
  later without touching callers.
- **`modules/video_import/masking.py`** — real `mask_frame(jpg_bytes, *,
  drop_zero_face=True)`: decode → grayscale → `detectMultiScale` → Gaussian-blur
  each face bbox (expanded margin, large odd kernel) → re-encode JPEG.
  **Fail-closed**: any decode/detect/blur/encode error → `failed` (drop, never
  store original). `faces_blurred` must equal `faces_detected`. Zero-face frames
  dropped by default (`drop_zero_face`), conservative until compliance accepts
  keeping them.
- **`core/audit_events.py`** — `SERVER_MASKING_APPLIED`
  {timestamp_ms, faces_detected, faces_blurred} + `SERVER_MASKING_FAILED`
  {timestamp_ms, reason}; locked-map test updated.
- **`config/schema.py`** — `FeatureFlagsConfig.video_import_drop_zero_face_frames
  = True`.
- **`api/v1/video_import.py::_extract_and_mask_frames`** — on `success`: validate
  a server-issued `MaskingProof` (same `core.types.MaskingProof` the iOS path
  uses), `put_object` the masked JPEG to `frames/{sid}/{ts}.jpg`, emit
  `SERVER_MASKING_APPLIED`. On `failed`: emit `SERVER_MASKING_FAILED`, drop.
- **`requirements.txt`** — `opencv-python-headless`, `numpy`. **`Dockerfile`** —
  `libglib2.0-0` (opencv-headless runtime).

Reuses: `MaskingProof`/`core.types`, `get_s3_client`/`FRAMES_BUCKET`,
`write_audit`, the existing `frames/{sid}/{ts}.jpg` key shape the vision
pipeline already reads.

## Acceptance criteria
- [ ] AC-1: `mask_frame` fails closed — corrupt bytes, empty bytes, and a detector that raises all return `status="failed", image_bytes=None` (never the original) — `pytest tests/unit/test_video_import_masking.py`.
- [ ] AC-2: when the cascade reports a face, every detected face is blurred (bbox pixel variance changes) and `faces_blurred == faces_detected`, `status="success"`.
- [ ] AC-3: zero-face frame → dropped when `drop_zero_face=True`; kept (re-encoded, no blur) when `False`.
- [ ] AC-4: orchestrator stores a masked frame to `frames/{sid}/{ts}.jpg` + emits `SERVER_MASKING_APPLIED` on success; emits `SERVER_MASKING_FAILED` + stores nothing on failure — orchestrator/helper unit test.
- [ ] AC-5: audit locked-map + kwargs whitelist updated.

## DRY / SOLID check
- **Reuse**: `MaskingProof` (same contract as iOS frame path), `get_s3_client`/
  `FRAMES_BUCKET`, `frames/{sid}/{ts}.jpg` key shape, `write_audit`.
- **OCP**: detector swap-able behind `mask_frame`; orchestrator unchanged by future detector upgrades.
- **Fail-closed (P0-01/02)**: the only path returning bytes is all-faces-blurred (or explicit keep-zero-face); no path stores the original.

## Out of scope
Enabling the flag (compliance gate), S3 bucket/KMS/lifecycle/CORS Terraform,
Stage 2 auto-advance, admin endpoints, web UI. DNN/MediaPipe upgrade (future).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_video_import_*.py tests/unit/test_audit_events.py -q`
2. `cd backend && python3 -m pytest tests/unit -q`
3. `cd backend && python3 -c "import app.main"`

## Security implications
**This is the compliance-critical slice.** Server-side masking is a new trust
boundary (transient unmasked PHI inside the backend). Mitigated: detection is
local (no managed CV API); fail-closed (drop on any error, never store the
original); zero-face frames dropped by default; every stored frame carries a
`SERVER_MASKING_APPLIED` audit row + a `MaskingProof`; the whole path stays
behind `video_import_enabled=False`. **Do not enable the flag in a PHI env
without compliance sign-off.**
