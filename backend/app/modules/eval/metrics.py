"""Deterministic per-note eval metrics (EVAL-1).

One implementation, shared by the CLI harness (`scripts/grounded_synthesis_eval.py`)
and the eval-lab runs endpoint (`admin/eval.py`), so a note scores the same
whether you run it offline or read it in the UI. No model call — every number
is derived from the note JSON + the transcript's segment ids.
"""

from __future__ import annotations

from app.core.types import Note, Transcript


def valid_source_ids(transcript: Transcript) -> set[str]:
    """The anchorable source ids we can verify a claim against — the
    transcript's segment ids. Visual/screen frame ids aren't in the
    transcript, so a claim citing only a frame is counted grounded only if it
    ALSO cites a real segment (conservative, matches the CLI harness)."""
    return {s.id for s in transcript.segments}


def compute_grounding_metrics(note: Note, valid_ids: set[str]) -> dict:
    """Objective grounding/quality metrics for one note. Deterministic."""
    claims = [c for s in note.sections for c in s.claims]
    total = len(claims)

    def claim_grounded(c) -> bool:
        ids = c.all_source_ids
        return bool(ids) and all(i in valid_ids for i in ids)

    grounded = sum(1 for c in claims if claim_grounded(c))
    ap = [
        c
        for s in note.sections
        if s.id in ("assessment", "plan")
        for c in s.claims
    ]
    ap_multi = sum(1 for c in ap if c.additional_sources)
    populated = [s for s in note.sections if s.status == "populated"]
    present = [s for s in note.sections if s.status != "pending_video"]
    ap_sections = {
        s.id
        for s in note.sections
        if s.id in ("assessment", "plan") and s.status == "populated"
    }

    return {
        "total_claims": total,
        "grounding_rate": round(grounded / total, 3) if total else 1.0,
        "ungrounded_claims": total - grounded,
        "ap_populated": len(ap_sections) == 2,
        "ap_claims": len(ap),
        "multi_anchor_rate": round(ap_multi / len(ap), 3) if ap else 0.0,
        "section_completeness": (
            round(len(populated) / len(present), 3) if present else 0.0
        ),
    }
