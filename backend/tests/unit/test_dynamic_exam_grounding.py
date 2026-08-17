"""General safeguards for named dynamic physical-examination manoeuvres."""

from __future__ import annotations

import json
import uuid

from app.core.types import (
    FrameCaption,
    Note,
    NoteSection,
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.providers.note_gen.shared import (
    build_user_prompt,
    parse_note_response,
)
from app.modules.vision.service import (
    _section_focus_block,
    merge_visual_citations,
)


def _transcript(*segments: tuple[str, str]) -> Transcript:
    return Transcript(
        session_id=str(uuid.uuid4()),
        provider_used="assemblyai",
        segments=[
            TranscriptSegment(
                id=segment_id,
                start_ms=index * 1_000,
                end_ms=(index + 1) * 1_000,
                text=text,
            )
            for index, (segment_id, text) in enumerate(segments)
        ],
    )


def _template() -> Template:
    return Template(
        key="general_exam",
        display_name="General examination",
        sections=[
            TemplateSection(
                id="physical_exam",
                title="Physical exam",
                required=True,
                description=("Document examination findings, named manoeuvres, side, and result."),
            ),
            TemplateSection(
                id="assessment",
                title="Assessment",
                required=True,
            ),
        ],
    )


def _note() -> Note:
    return Note(
        session_id=str(uuid.uuid4()),
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="general_exam",
        sections=[
            NoteSection(
                id="physical_exam",
                title="Physical exam",
                status="pending_video",
                claims=[],
            ),
            NoteSection(
                id="assessment",
                title="Assessment",
                status="not_captured",
                claims=[],
            ),
        ],
    )


def _caption(
    description: str,
    *,
    evidence_kind: str = "frame",
) -> FrameCaption:
    return FrameCaption(
        frame_id="frame_001",
        session_id="session_001",
        timestamp_ms=1_000,
        audio_anchor_id="seg_001",
        provider_used="gemini",
        visual_description=description,
        confidence="high",
        integration_status="ENRICHES",
        evidence_kind=evidence_kind,
    )


def test_stage1_prompt_makes_named_manoeuvres_atomic_in_both_contracts() -> None:
    transcript = _transcript(("seg_001", "McMurray is positive on the left."))

    full_prompt = build_user_prompt(transcript, _template(), stage=1)
    compact_prompt = build_user_prompt(
        transcript,
        _template(),
        stage=1,
        compact_stage1=True,
    )

    for prompt in (full_prompt, compact_prompt):
        assert "Treat every named examination manoeuvre as an atomic finding" in prompt
        assert "Never merge two tests" in prompt
        assert "'X or Y', 'X/Y', or 'X-type manoeuvre'" in prompt
        assert "omit that identity/result rather than guessing" in prompt


def test_parser_drops_model_added_test_ambiguity_but_keeps_distinct_results() -> None:
    transcript = _transcript(
        (
            "seg_001",
            "I am performing the McMurray test on the left. That reproduces pain.",
        ),
        ("seg_002", "Patellar grind is painless on the left."),
        ("seg_003", "Possible meniscal pathology or early osteoarthritis."),
    )
    payload = {
        "sections": [
            {
                "id": "physical_exam",
                "title": "Physical exam",
                "status": "populated",
                "claims": [
                    {
                        "id": "bad_alternative",
                        "text": (
                            "A patellar/provocation test (consistent with McMurray or patellar grind) elicited pain."
                        ),
                        "source_id": "seg_001",
                        "additional_sources": [{"source_id": "seg_002"}],
                    },
                    {
                        "id": "mcmurray",
                        "text": "McMurray test on the left reproduced pain.",
                        "source_id": "seg_001",
                    },
                    {
                        "id": "patellar",
                        "text": "Patellar grind was painless on the left.",
                        "source_id": "seg_002",
                    },
                ],
            },
            {
                "id": "assessment",
                "title": "Assessment",
                "status": "populated",
                "claims": [
                    {
                        "id": "bad_type",
                        "text": "A McMurray-type manoeuvre elicited pain.",
                        "source_id": "seg_001",
                    },
                    {
                        "id": "valid_differential",
                        "text": "Possible meniscal pathology or early osteoarthritis.",
                        "source_id": "seg_003",
                    },
                ],
            },
        ]
    }

    note = parse_note_response(
        json.dumps(payload),
        transcript,
        _template(),
        stage=1,
        provider_name="anthropic",
    )

    exam_ids = {claim.id for claim in note.get_section("physical_exam").claims}
    assessment_ids = {claim.id for claim in note.get_section("assessment").claims}
    assert exam_ids == {"mcmurray", "patellar"}
    assert assessment_ids == {"valid_differential"}


def test_parser_preserves_ambiguity_explicitly_dictated_by_the_clinician() -> None:
    transcript = _transcript(
        (
            "seg_001",
            "This is either a McMurray test or a patellar grind; the recording is unclear.",
        )
    )
    payload = {
        "sections": [
            {
                "id": "physical_exam",
                "title": "Physical exam",
                "status": "populated",
                "claims": [
                    {
                        "id": "dictated_uncertainty",
                        "text": "The manoeuvre was a McMurray test or a patellar grind.",
                        "source_id": "seg_001",
                    }
                ],
            }
        ]
    }

    note = parse_note_response(
        json.dumps(payload),
        transcript,
        _template(),
        stage=1,
        provider_name="anthropic",
    )

    assert [claim.id for claim in note.get_section("physical_exam").claims] == ["dictated_uncertainty"]


def test_physical_exam_focus_distinguishes_still_from_temporal_evidence() -> None:
    note = _note()
    template = _template()

    frame_focus = _section_focus_block(
        template,
        note,
        "seg_001",
        evidence_kind="frame",
    )
    clip_focus = _section_focus_block(
        template,
        note,
        "seg_001",
        evidence_kind="clip",
    )

    assert frame_focus is not None
    assert "A still frame cannot establish" in frame_focus
    assert "Never name or guess a test from hand position" in frame_focus
    assert clip_focus is not None
    assert "clip shows the complete motion and observable result" in clip_focus
    assert "never guess or offer alternative test identities" in clip_focus


def test_frame_merge_removes_only_unresolved_manoeuvre_sentences() -> None:
    note = _note()
    caption = _caption(
        "The knee is in near-full extension. No swelling is visible. "
        "The specific manoeuvre being initiated cannot be determined from "
        "this frame alone. Hand placement is consistent with palpation or "
        "an effusion assessment."
    )

    merge_visual_citations(note, [caption], _template())

    claims = note.get_section("physical_exam").claims
    assert len(claims) == 1
    assert "near-full extension" in claims[0].text
    assert "No swelling is visible" in claims[0].text
    assert "specific manoeuvre" not in claims[0].text
    assert "palpation or" not in claims[0].text


def test_purely_unresolved_frame_does_not_populate_physical_exam() -> None:
    note = _note()
    caption = _caption("The specific manoeuvre cannot be determined from this frame alone.")

    merge_visual_citations(note, [caption], _template())

    assert note.get_section("physical_exam").claims == []
    assert note.get_section("physical_exam").status == "not_captured"


def test_temporal_clip_keeps_a_supported_named_manoeuvre() -> None:
    note = _note()
    caption = _caption(
        "Across the clip, the McMurray test reproduces pain during rotation.",
        evidence_kind="clip",
    )

    merge_visual_citations(note, [caption], _template())

    claims = note.get_section("physical_exam").claims
    assert len(claims) == 1
    assert "McMurray test reproduces pain" in claims[0].text
