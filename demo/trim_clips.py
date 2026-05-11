#!/usr/bin/env python3
"""
Trim master.mp4 into 9 scene clips for the HyperFrames composition.

Reads milestones.json produced by run_demo_perry.py and lifts each scene
out of the master at the matching wall-clock window. Each clip is
re-encoded to CFR 30 fps so the GSAP timeline can scrub it cleanly (VFR
sources cause `-t` to under/overshoot, which then desyncs against
narration.wav in the composition).

Scene boundaries (composition time → master target):
  s1-intro        4.0  →  M2.0  (login → dashboard)            8.5 s
  s2-profile     12.5  →  M10.5 (profile top + scrolls)       17.7 s
  s3-capture     30.2  →  M28.2 (capture mode picker)         13.3 s
  s4-encounter   43.5  →  M41.5 (context + consent)           20.0 s
  s5-recording   63.5  →  M61.5 (recording dwell)             19.5 s
  s6-live-note   83.0  →  M_note_ready                         9.5 s
  s7-multimodal  92.5  →  M_stage1_open                       18.5 s
  s8-final      111.0  →  M_stage1_open + 18.5                17.0 s
  s9-ending     128.0  →  M_stage1_open + 35.5                 4.0 s

Sections 1–5 are paced (wait_until anchors), so their start time in the
master is deterministic. Sections 6–9 depend on when the ML pipeline
finishes returning the note — we use the `note_ready` and `stage1_open`
milestones as anchors instead of fixed master timestamps.
"""

from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MASTER = ROOT / "master.mp4"
MASTER_CFR = ROOT / "master-cfr.mp4"
MILESTONES = ROOT / "milestones.json"
CLIPS = ROOT / "video" / "clips"


def run(cmd: list[str], *, check: bool = True) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def re_encode_cfr() -> None:
    """Re-encode master.mp4 to CFR 30 fps. Simulator recordings come out
    VFR (variable frame rate) and ffmpeg `-t` flags are unreliable
    against VFR sources — every section ends up a frame or two short and
    the 9-scene chain drifts ~0.5s by the end."""
    if MASTER_CFR.exists():
        MASTER_CFR.unlink()
    run([
        "ffmpeg", "-y",
        "-i", str(MASTER),
        "-r", "30",
        "-g", "30",
        "-keyint_min", "30",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        str(MASTER_CFR),
    ])


def trim_clip(src: Path, start: float, duration: float, out: Path) -> None:
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        str(out),
    ])


def load_milestones() -> dict[str, float]:
    if not MILESTONES.exists():
        raise SystemExit(f"missing {MILESTONES} — run run_demo_perry.py first")
    data = json.loads(MILESTONES.read_text())
    return {name: t for name, t in data["milestones"]}


def main() -> None:
    if not MASTER.exists():
        raise SystemExit(f"missing {MASTER} — run run_demo_perry.py first")
    print(f"→ re-encoding {MASTER.name} → {MASTER_CFR.name} (CFR 30fps)")
    re_encode_cfr()

    ms = load_milestones()
    print(f"→ loaded {len(ms)} milestones from {MILESTONES.name}")
    for k, v in sorted(ms.items(), key=lambda kv: kv[1]):
        print(f"     {k:<24s} {v:>7.2f}s")

    # Deterministic wall-clock anchors for s1-s5 (paced via wait_until in
    # run_demo_perry.py). Sections 6-9 use milestone-relative anchors.
    note_ready = ms.get("note_ready")
    stage1_open = ms.get("stage1_open")
    if note_ready is None or stage1_open is None:
        raise SystemExit("milestones missing note_ready / stage1_open — "
                         "did Generate Note succeed?")

    plan = [
        ("s1-intro.mp4",        2.0,                 8.5),
        ("s2-profile.mp4",     10.5,                17.7),
        ("s3-capture-mode.mp4",28.2,                13.3),
        ("s4-encounter.mp4",   41.5,                20.0),
        ("s5-recording.mp4",   61.5,                19.5),
        # The fade between "Note Ready" and Stage 1 is ~9.5s of footage —
        # we want note_ready - 1.5 → +8.0 so we see the toast, the tap,
        # and the first frame of the Stage 1 view.
        ("s6-live-note.mp4",   max(0.0, note_ready - 1.5), 9.5),
        ("s7-multimodal.mp4",  stage1_open,         18.5),
        ("s8-final.mp4",       stage1_open + 18.5,  17.0),
        ("s9-ending.mp4",      stage1_open + 35.5,   4.0),
    ]

    for name, start, dur in plan:
        out = CLIPS / name
        print(f"\n→ {name}  start={start:.2f}s  duration={dur:.2f}s")
        trim_clip(MASTER_CFR, start, dur, out)

    print("\n✓ all 9 clips trimmed → video/clips/")


if __name__ == "__main__":
    main()
