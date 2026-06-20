# Plan — VID-07

## Task
DNN face detector upgrade (OpenCV res10 SSD) with Haar fallback.

## Why
Deferred from VID-04. Higher recall than Haar (esp. off-angle faces) without
breaking the build or vendoring a binary, and without weakening fail-closed.

## Approach
- `masking.py`: `_dnn_net()` lazily loads res10 SSD from FACE_DETECTOR_MODEL_DIR
  (default /app/models); `_detect_faces(img)` uses DNN when loaded, else the
  Haar cascade. `mask_frame` routes detection through `_detect_faces` — blur +
  fail-closed logic unchanged.
- `Dockerfile`: BEST-EFFORT download of the res10 prototxt + caffemodel at build
  (|| warns, never fails the build) → prod gets DNN, CI/local fall back to Haar.

## Acceptance criteria
- [ ] `_detect_faces` parses SSD output when a net is loaded; falls back to Haar when not (unit-tested).
- [ ] All existing masking fail-closed/blur tests still pass (Haar path).
- [ ] Build never fails on a download error; runtime falls back to Haar.

## Out of scope
Infra (VID-08), web (VID-09), multipart (VID-10).

## Test plan
1. `python3 -m pytest tests/unit/test_video_import_masking.py -q`
2. `python3 -m pytest tests/unit -q`

## Security implications
Detection stays local/in-process (no managed CV API). Fail-closed unchanged.
Still dark behind `video_import_enabled`.
