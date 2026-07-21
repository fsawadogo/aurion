"""Grounded Synthesis eval harness (v3.2, #551 / GS-9 sign-off input).

Produces the quantitative half of the clinical/regulatory review: a
**descriptive-baseline vs grounded** comparison over the SAME encounters.

This script does NOT generate notes and does NOT invent numbers. You feed it
two sets of already-generated Stage-1 notes (the same transcripts run with the
flag OFF, then ON) plus the transcripts; it computes objective metrics and
writes a Markdown report the reviewer signs against.

How to produce the inputs (inside the dev/pilot env, on NON-PHI or
consented eval encounters):
  1. With `grounded_synthesis_enabled = false`, run/export Stage-1 notes for the
     eval transcripts  → `descriptive/<session>.json`
  2. Flip the flag ON (a throwaway eval window), re-run the SAME transcripts,
     export → `grounded/<session>.json`, then flip OFF again.
  3. Export the matching transcripts → `transcripts/<session>.json`
  4. `python -m scripts.grounded_synthesis_eval --descriptive descriptive \
        --grounded grounded --transcripts transcripts --out report.md`

Each `<session>.json` is a Note (app.core.types.Note) dump; each transcript is a
Transcript dump. Files are matched by filename stem.

Metrics (all objective, no clinical judgement — that's the reviewer's job):
  - grounding_rate      : % of claims whose EVERY source anchor (primary +
                          additional_sources) is a real transcript/visual id.
                          The core safety number — must be ~1.0 in grounded mode.
  - ungrounded_claims   : count of claims with any invalid/absent anchor (target 0)
  - ap_populated        : assessment AND plan sections populated (synthesis lands)
  - ap_claims           : # claims in assessment+plan (synthesis volume)
  - multi_anchor_rate   : % of A&P claims citing >1 source (synthesis depth)
  - section_completeness : % of populated (non-pending) sections
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.types import Note, Transcript

# EVAL-1: one implementation, shared with the eval-lab endpoint. Kept as
# module-local aliases so the rest of this script (and its callers) are
# unchanged.
from app.modules.eval.metrics import compute_grounding_metrics
from app.modules.eval.metrics import valid_source_ids as _valid_source_ids

__all__ = ["compute_grounding_metrics"]


def build_comparison_report(rows: list[dict]) -> str:
    """rows: [{session, descriptive:{...}, grounded:{...}}]. Returns Markdown."""
    def avg(side: str, key: str) -> float:
        vals = [r[side][key] for r in rows if r.get(side)]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    lines = [
        "# Grounded Synthesis — descriptive vs grounded comparison",
        "",
        f"Encounters compared: **{len(rows)}**. Same transcripts, flag OFF vs ON.",
        "",
        "## Aggregate (means)",
        "| Metric | Descriptive (OFF) | Grounded (ON) |",
        "|---|---|---|",
    ]
    for key, label in [
        ("grounding_rate", "Grounding rate (↑, target ~1.0)"),
        ("ungrounded_claims", "Ungrounded claims / note (↓, target 0)"),
        ("section_completeness", "Section completeness (↑)"),
        ("ap_claims", "A&P claims / note"),
        ("multi_anchor_rate", "A&P multi-source rate"),
    ]:
        lines.append(f"| {label} | {avg('descriptive', key)} | {avg('grounded', key)} |")
    ap_off = round(sum(1 for r in rows if r.get("descriptive", {}).get("ap_populated")) / len(rows), 3) if rows else 0
    ap_on = round(sum(1 for r in rows if r.get("grounded", {}).get("ap_populated")) / len(rows), 3) if rows else 0
    lines.append(f"| A&P populated (both sections) | {ap_off} | {ap_on} |")
    lines += [
        "",
        "## Per-encounter grounding rate + ungrounded count",
        "| Session | OFF grounding / ungrounded | ON grounding / ungrounded |",
        "|---|---|---|",
    ]
    for r in rows:
        d, g = r.get("descriptive", {}), r.get("grounded", {})
        lines.append(
            f"| {r['session']} | {d.get('grounding_rate','-')} / {d.get('ungrounded_claims','-')} "
            f"| {g.get('grounding_rate','-')} / {g.get('ungrounded_claims','-')} |"
        )
    lines += [
        "",
        "## Reviewer checks (the safety bar — fill in)",
        "- [ ] Grounded **grounding_rate is ~1.0** and **ungrounded_claims is 0** "
        "(no synthesized statement lacks a real source).",
        "- [ ] Spot-read N grounded A&P sections: each conclusion is supported by "
        "its cited segment(s); no fabrication / over-reach.",
        "- [ ] Grounded **physician_edit_rate** (from `pilot_metrics`, measured "
        "post-enable) is ≤ descriptive baseline.",
        "",
        "_Numbers are objective; the clinical acceptability judgement is the "
        "reviewer's (see the sign-off record).__",
    ]
    return "\n".join(lines) + "\n"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Grounded Synthesis descriptive-vs-grounded eval")
    ap.add_argument("--descriptive", required=True, type=Path, help="dir of OFF Note JSONs")
    ap.add_argument("--grounded", required=True, type=Path, help="dir of ON Note JSONs")
    ap.add_argument("--transcripts", required=True, type=Path, help="dir of Transcript JSONs")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    rows: list[dict] = []
    for tpath in sorted(a.transcripts.glob("*.json")):
        stem = tpath.stem
        d_path, g_path = a.descriptive / f"{stem}.json", a.grounded / f"{stem}.json"
        if not (d_path.exists() and g_path.exists()):
            print(f"skip {stem}: missing descriptive or grounded note")
            continue
        valid = _valid_source_ids(Transcript.model_validate(_load(tpath)))
        rows.append({
            "session": stem,
            "descriptive": compute_grounding_metrics(Note.model_validate(_load(d_path)), valid),
            "grounded": compute_grounding_metrics(Note.model_validate(_load(g_path)), valid),
        })
    a.out.write_text(build_comparison_report(rows), encoding="utf-8")
    print(f"wrote {a.out} ({len(rows)} encounters)")


if __name__ == "__main__":
    main()
