# Backend test fixtures

Tiny synthesized assets used by tests AND by operators running local
`curl` against new diagnostic endpoints. Keep them small, content-free,
and reproducible.

## `probe_clip.mp4`

* **Purpose:** payload for the `POST /api/v1/admin/probe/vision-clip`
  endpoint and for `tests/integration/test_vision_clip_probe.py`.
* **Properties:**
  - 320x240 solid blue, 2.0s, H.264 (`yuv420p`), **no audio track**.
  - ~5 KB on disk (`-tune zerolatency` keeps the bitrate
    near-minimum for a single-color stream).
  - Deliberately content-free: there is NOTHING clinical visible.
    Even though the probe endpoint does not persist the bytes, the
    fixture is committed to the repo and must remain safe to ship in
    any context.
* **Regenerate:**
  ```bash
  ffmpeg -f lavfi -i "color=c=blue:s=320x240:d=2" \
         -c:v libx264 -pix_fmt yuv420p -tune zerolatency \
         -an -y backend/tests/fixtures/probe_clip.mp4
  ```
* **Verify:**
  ```bash
  ffprobe -v error -show_streams backend/tests/fixtures/probe_clip.mp4
  ```
  Expected: one stream with `codec_name=h264`, `codec_type=video`,
  `duration~2.0`, no `codec_type=audio` line.

## Adding new fixtures

Keep them tiny (< 50 KB for video, < 10 KB for images). Document the
regeneration recipe here so a future contributor can rebuild without
guessing the `ffmpeg` flags.
