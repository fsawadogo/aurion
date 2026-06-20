# Plan — VID-03

## Task
VID-03 — Server-side frame extraction at trigger windows + masking **stub**
(drops all frames). Wires the frame path with zero face storage.

## Why
Stage B of the design (`AURION-CODING-WORKFLOW.md` thin slices). Lands the
ffmpeg frame-extraction + the `mask_frame` call site so VID-04 only swaps the
stub for real OpenCV masking. The stub drops every frame → vision degrades to
frames-absent (identical to audio-only) → no real face ever stored. Still dark
behind `video_import_enabled`.

## Approach
- `config/schema.py` — `PipelineConfig.video_import_fps` (default 1) for the
  per-window sample rate.
- `modules/video_import/extraction.py` — `extract_frame_at_ms(video_path, ms)`
  (single `ffmpeg -ss` seek → JPEG bytes) and `extract_frames_at_windows(
  video_path, windows, fps)` (sample each `(start_ms,end_ms)` window at `fps`,
  return `[(timestamp_ms, jpg_bytes)]`).
- `modules/video_import/masking.py` (new) — `MaskedFrameResult` dataclass +
  `mask_frame(jpg_bytes)` **stub that always returns failed** (no detection, no
  blur). The real OpenCV implementation lands in VID-04 behind the same
  signature.
- `api/v1/video_import.py` orchestrator — keep the raw video on task-local disk
  through frame extraction: download → extract audio → run_stage1 → load the
  persisted transcript → compute trigger windows (reuse
  `vision.service.get_frame_window_ms`) → `extract_frames_at_windows` → `mask_frame`
  each (all dropped in VID-03; nothing written to S3) → record
  `frames_extracted`/`frames_masked`/`frames_dropped` on the job → purge raw
  video → complete. Fail-closed purge unchanged.

Reuses: `get_frame_window_ms` (vision), `extract_audio`/`jobs`/`purge_raw_video`
(VID-01/02), the persisted `TranscriptModel`.

## Acceptance criteria
- [ ] AC-1: `extract_frames_at_windows` returns one+ JPEG per window with timestamps inside the window — `pytest tests/unit/test_video_import_frame_extraction.py`.
- [ ] AC-2: `mask_frame` stub returns `status="failed"`, `image_bytes is None` for any input (never stores a face) — `pytest tests/unit/test_video_import_masking_stub.py`.
- [ ] AC-3: orchestrator records frame counters (extracted = N, masked = 0, dropped = N) and writes NO frame to S3 when the stub drops all — orchestrator unit test extended.
- [ ] AC-4: zero trigger segments → zero frames extracted, job still completes (pilot reality with empty trigger lists).

## DRY / SOLID check
- **Reuse**: `get_frame_window_ms` (vision), ffmpeg-subprocess shape from
  `extract_audio`. `mask_frame` signature is the VID-04 seam.
- **SRP**: extraction = ffmpeg; masking = the (stub) face gate; orchestrator =
  sequencing.
- **OCP**: VID-04 swaps the masking impl behind the unchanged `mask_frame`
  signature — no orchestrator change needed.

## Out of scope
Real masking (VID-04), S3 frame storage + `SERVER_MASKING_*` audit (VID-04,
since the stub stores nothing), Stage 2 auto-advance, web UI, admin endpoints.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_video_import_*.py -q`
2. `cd backend && python3 -m pytest tests/unit -q`
3. `cd backend && python3 -c "import app.main"`

## Security implications
**No new PHI surface** — the masking stub drops every frame, so no face image
is ever written to S3 in this slice (frames-absent, same as audio-only). The
real masking trust-boundary is VID-04 (compliance-gated). Raw video still
purged with audit proof; all routes 404 when the flag is off.
