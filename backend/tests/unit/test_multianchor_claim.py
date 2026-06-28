"""GS-6 (#548) — NoteClaim multi-anchor (additional_sources), back-compat.

A synthesized A&P claim may cite several findings; a descriptive claim cites
one. The extra anchors live in `additional_sources` (default empty, so every
existing claim/parse path is unchanged). Not flag-gated — an inert schema
capability populated only by grounded synthesis.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.types import ClaimSource, NoteClaim, Transcript, TranscriptSegment
from app.modules.note_gen.service import get_template
from app.modules.providers.note_gen.shared import (
    NOTE_RESPONSE_SCHEMA,
    parse_note_response,
)


def _transcript() -> Transcript:
    return Transcript(
        session_id="00000000-0000-0000-0000-000000000000",
        provider_used="assemblyai",
        segments=[
            TranscriptSegment(id="seg_002", start_ms=0, end_ms=1000, text="Lachman positive on the left."),
            TranscriptSegment(id="seg_005", start_ms=1000, end_ms=2000, text="MRI left knee reviewed."),
        ],
    )


def test_back_compat_no_additional_sources():
    # AC-1: a normal single-anchor claim is unchanged.
    c = NoteClaim(id="c1", text="x", source_type="transcript", source_id="seg_001")
    assert c.additional_sources == []
    assert c.all_source_ids == ["seg_001"]


def test_multi_anchor_all_source_ids():
    # AC-2: extra anchors round-trip; all_source_ids = primary + extras in order.
    c = NoteClaim(
        id="c1",
        text="Working assessment: rotator cuff pathology.",
        source_type="transcript",
        source_id="seg_014",
        additional_sources=[
            ClaimSource(source_id="seg_021", source_quote="positive Hawkins"),
            ClaimSource(source_id="frame_07", source_quote="restricted IR"),
        ],
    )
    assert c.all_source_ids == ["seg_014", "seg_021", "frame_07"]


def test_claim_source_rejects_empty_id():
    # AC-3: an extra anchor must still be a real (non-empty) source id.
    with pytest.raises(ValidationError):
        ClaimSource(source_id="")


def test_schema_lists_additional_sources_optional():
    # AC-4: schema allows the field but does NOT require it (descriptive output unchanged).
    claim_props = NOTE_RESPONSE_SCHEMA["properties"]["sections"]["items"]["properties"][
        "claims"
    ]["items"]
    assert "additional_sources" in claim_props["properties"]
    assert "additional_sources" not in claim_props["required"]


def test_parser_populates_additional_sources():
    # AC-5: the LLM-output parser carries extra anchors through; malformed
    # extra entries (no source_id) are dropped, not crashed on.
    template = get_template("orthopedic_surgery")
    payload = {
        "sections": [
            {
                "id": "assessment",
                "status": "populated",
                "claims": [
                    {
                        "id": "a1",
                        "text": "Working assessment: partial ACL tear, left.",
                        "source_type": "transcript",
                        "source_id": "seg_002",
                        "source_quote": "Lachman positive on the left",
                        "additional_sources": [
                            {"source_id": "seg_005", "source_quote": "MRI left knee"},
                            {"source_quote": "no id — should be dropped"},
                        ],
                    }
                ],
            }
        ]
    }
    note = parse_note_response(
        json.dumps(payload), _transcript(), template, stage=1, provider_name="test"
    )
    claim = next(c for s in note.sections if s.id == "assessment" for c in s.claims)
    assert claim.all_source_ids == ["seg_002", "seg_005"]
