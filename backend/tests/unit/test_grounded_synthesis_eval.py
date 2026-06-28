"""Tests for the GS-9 eval harness metrics (scripts/grounded_synthesis_eval.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.core.types import ClaimSource, Note, NoteClaim, NoteSection

# Load the script module (lives under scripts/, not a package).
_spec = importlib.util.spec_from_file_location(
    "gs_eval", Path(__file__).resolve().parents[2] / "scripts" / "grounded_synthesis_eval.py"
)
gs_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs_eval)


def _note(sections):
    return Note(session_id="s", stage=1, version=1, provider_used="anthropic", specialty="orthopedic_surgery", sections=sections)


def _claim(cid, sid, extra=None):
    return NoteClaim(
        id=cid, text="x", source_type="transcript", source_id=sid,
        additional_sources=[ClaimSource(source_id=e) for e in (extra or [])],
    )


def test_fully_grounded_multi_anchor_note():
    note = _note([
        NoteSection(id="assessment", status="populated", claims=[_claim("a1", "seg_001", ["seg_002"])]),
        NoteSection(id="plan", status="populated", claims=[_claim("p1", "seg_002")]),
    ])
    m = gs_eval.compute_grounding_metrics(note, {"seg_001", "seg_002"})
    assert m["grounding_rate"] == 1.0
    assert m["ungrounded_claims"] == 0
    assert m["ap_populated"] is True
    assert m["ap_claims"] == 2
    assert m["multi_anchor_rate"] == 0.5  # 1 of 2 A&P claims cites >1 source


def test_ungrounded_claim_is_counted():
    note = _note([
        NoteSection(id="assessment", status="populated", claims=[
            _claim("a1", "seg_001"),
            _claim("a2", "seg_999"),            # invalid primary
            _claim("a3", "seg_001", ["seg_404"]),  # invalid additional anchor
        ]),
    ])
    m = gs_eval.compute_grounding_metrics(note, {"seg_001"})
    assert m["ungrounded_claims"] == 2
    assert m["grounding_rate"] == round(1 / 3, 3)


def test_report_builds():
    rows = [{
        "session": "sess1",
        "descriptive": gs_eval.compute_grounding_metrics(
            _note([NoteSection(id="assessment", status="populated", claims=[_claim("a", "seg_001")])]), {"seg_001"}),
        "grounded": gs_eval.compute_grounding_metrics(
            _note([
                NoteSection(id="assessment", status="populated", claims=[_claim("a", "seg_001", ["seg_002"])]),
                NoteSection(id="plan", status="populated", claims=[_claim("p", "seg_002")]),
            ]), {"seg_001", "seg_002"}),
    }]
    md = gs_eval.build_comparison_report(rows)
    assert "descriptive vs grounded" in md
    assert "Grounding rate" in md and "sess1" in md
