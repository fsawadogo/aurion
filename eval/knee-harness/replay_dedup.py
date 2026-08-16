"""Replay a captured run's visual claims through VIS-09 dedup — before/after.

Answers "did the fix help?" without a deploy: it takes the captions a real
Stage 2 actually produced, runs the live ``classify_conflicts`` over them, and
reports what would have survived.

    cd eval/knee-harness
    python replay_dedup.py                       # newest vision run
    python replay_dedup.py --run <file.json>

What it does NOT do: prove the merge writes fewer claims. It proves the
classifier marks the duplicates. The merge already filters REPEATS
(vision/service.py) and is unchanged by VIS-09.
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))

from app.core.types import FrameCaption, Note, NoteSection  # noqa: E402
from app.modules.vision.service import classify_conflicts  # noqa: E402


def _as_caption(text: str, idx: int) -> FrameCaption:
    return FrameCaption(
        frame_id=f"frame_{idx:05d}",
        session_id="replay",
        timestamp_ms=idx * 5000,
        audio_anchor_id="seg_001",
        provider_used="anthropic",
        visual_description=text,
        confidence="high",
        confidence_reason="",
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="path to a run JSON (default: newest with vision)")
    args = ap.parse_args()

    if args.run:
        path = pathlib.Path(args.run)
    else:
        candidates = [
            p for p in sorted(glob.glob(str(HERE / "runs" / "*.json")), reverse=True)
            if json.loads(pathlib.Path(p).read_text(encoding="utf-8")).get("note_vision")
        ]
        if not candidates:
            print("No captured run with a vision note. Capture one first.")
            return 1
        path = pathlib.Path(candidates[0])

    run = json.loads(path.read_text(encoding="utf-8"))
    note_v = run.get("note_vision")
    if not note_v:
        print(f"{path.name} has no vision note.")
        return 1

    print(f"run:  {run.get('label', path.name)}")
    print(f"file: {path.name}\n")

    grand_before = grand_after = 0
    for section in note_v["sections"]:
        visual = [
            c["text"] for c in section.get("claims", [])
            if c.get("source_type") == "visual"
        ]
        if not visual:
            continue

        caps = [_as_caption(t, i) for i, t in enumerate(visual)]
        note = Note(
            session_id="replay", stage=2, version=1, provider_used="anthropic",
            specialty="musculoskeletal", completeness_score=0.0,
            sections=[NoteSection(id=section["id"], status="populated", claims=[])],
        )
        classify_conflicts(caps, note)

        kept = [c for c in caps if c.integration_status == "ENRICHES"]
        before, after = len(caps), len(kept)
        grand_before += before
        grand_after += after
        pct = (1 - after / before) * 100 if before else 0
        print(f"  {section['id']:20} {before:3} -> {after:3} visual claims  "
              f"({pct:.0f}% collapsed)")
        for c in kept:
            print(f"       kept: {c.visual_description[:96]}")
        print()

    if grand_before:
        pct = (1 - grand_after / grand_before) * 100
        print(f"TOTAL visual claims: {grand_before} -> {grand_after} "
              f"({pct:.0f}% collapsed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
