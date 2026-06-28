"""GS-8 (#550) — grounding-gate guard. The differentiator: grounded synthesis is
safe only because these invariants hold regardless of mode.

Pins: (1) no anchorless claim is constructible; (2) the critique audit flags an
out-of-transcript primary AND a fabricated additional_source; (3) the mechanical
drop works; (4) a fully-grounded multi-anchor claim is recognised as valid.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.types import (
    ClaimSource,
    Note,
    NoteClaim,
    NoteSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.note_gen.critique import _apply_actions, _build_critique_prompt


def _transcript() -> Transcript:
    return Transcript(
        session_id="00000000-0000-0000-0000-000000000000",
        provider_used="assemblyai",
        segments=[
            TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="Lachman positive left."),
            TranscriptSegment(id="seg_002", start_ms=1000, end_ms=2000, text="MRI shows ACL tear."),
        ],
    )


def _note(claims: list[NoteClaim]) -> Note:
    return Note(
        session_id="s",
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[NoteSection(id="assessment", status="populated", claims=claims)],
    )


def test_anchorless_claim_impossible():
    # AC-1: a claim (or an extra anchor) can never be constructed without a source.
    with pytest.raises(ValidationError):
        NoteClaim(id="c", text="x", source_type="transcript", source_id="")
    with pytest.raises(ValidationError):
        ClaimSource(source_id="")


def test_critique_flags_invalid_primary_anchor():
    # AC-2: a claim citing a non-existent segment is marked valid=False.
    note = _note([
        NoteClaim(id="c1", text="bad", source_type="transcript", source_id="seg_999")
    ])
    prompt = _build_critique_prompt(note, _transcript())
    assert "src=seg_999 valid=False" in prompt


def test_critique_flags_fabricated_additional_source():
    # AC-3: a synthesized claim whose EXTRA anchor is fabricated is flagged.
    note = _note([
        NoteClaim(
            id="c1",
            text="Working assessment: ACL tear.",
            source_type="transcript",
            source_id="seg_001",
            additional_sources=[ClaimSource(source_id="seg_404")],
        )
    ])
    prompt = _build_critique_prompt(note, _transcript())
    assert "valid=True" in prompt          # primary is real
    assert "extra_valid=False" in prompt   # but the extra is fabricated


def test_fully_grounded_multi_anchor_is_valid():
    # AC-5: a synthesized claim with all anchors real → valid + extra_valid True.
    note = _note([
        NoteClaim(
            id="c1",
            text="Working assessment: ACL tear, supported by exam + MRI.",
            source_type="transcript",
            source_id="seg_001",
            additional_sources=[ClaimSource(source_id="seg_002")],
        )
    ])
    prompt = _build_critique_prompt(note, _transcript())
    assert "src=seg_001 valid=True" in prompt
    assert "extra_valid=True" in prompt


def test_apply_actions_drops_unanchored_claim():
    # AC-4: the mechanical grounding cleanup removes a flagged claim.
    note = _note([
        NoteClaim(id="keep", text="ok", source_type="transcript", source_id="seg_001"),
        NoteClaim(id="bad", text="ungrounded", source_type="transcript", source_id="seg_999"),
    ])
    applied = _apply_actions(
        note, [{"action": "drop_claim", "section_id": "assessment", "claim_id": "bad"}]
    )
    assert applied == 1
    ids = [c.id for s in note.sections for c in s.claims]
    assert ids == ["keep"]
