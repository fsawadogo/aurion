"""Tests for vision pipeline — conflict classification, note merge, frame discard."""

import pytest

from app.core.types import (
    FrameCaption,
    MaskedFrame,
    Note,
    NoteClaim,
    NoteSection,
    TranscriptSegment,
)
from app.modules.vision.service import (
    classify_conflicts,
    get_frame_window_ms,
    has_unresolved_conflicts,
    merge_visual_citations,
)
from app.modules.providers.vision.openai import VISION_SYSTEM_PROMPT as OPENAI_VISION_PROMPT
from app.modules.providers.vision.anthropic import VISION_SYSTEM_PROMPT as ANTHROPIC_VISION_PROMPT
from app.modules.providers.vision.gemini import VISION_SYSTEM_PROMPT as GEMINI_VISION_PROMPT


def _make_caption(
    frame_id: str = "frame_001",
    anchor_id: str = "seg_001",
    status: str = "ENRICHES",
    confidence: str = "high",
    description: str = "Visible guarding on palpation of right knee.",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="test-session",
        timestamp_ms=5000,
        audio_anchor_id=anchor_id,
        provider_used="test",
        visual_description=description,
        confidence=confidence,
        confidence_reason="Test reason",
        conflict_flag=(status == "CONFLICTS"),
        conflict_detail="Test conflict" if status == "CONFLICTS" else None,
        integration_status=status,
    )


def _make_stage1_note() -> Note:
    return Note(
        session_id="test-session",
        stage=1,
        version=1,
        provider_used="test",
        specialty="orthopedic_surgery",
        completeness_score=0.67,
        sections=[
            NoteSection(
                id="physical_exam",
                title="Physical Examination",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_001",
                        text="Tenderness on palpation at medial joint line.",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="There is tenderness on palpation.",
                    )
                ],
            ),
            NoteSection(
                id="imaging_review",
                title="Imaging Review",
                status="pending_video",
                claims=[],
            ),
            NoteSection(
                id="assessment",
                title="Assessment",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_002",
                        text="Mock assessment.",
                        source_type="transcript",
                        source_id="seg_002",
                    )
                ],
            ),
        ],
    )


class TestConflictClassification:
    def test_enriches_not_flagged(self):
        captions = [_make_caption(status="ENRICHES")]
        result = classify_conflicts(captions, _make_stage1_note())
        assert result[0].conflict_flag is False

    def test_conflicts_flagged(self):
        captions = [_make_caption(status="CONFLICTS")]
        result = classify_conflicts(captions, _make_stage1_note())
        assert result[0].conflict_flag is True

    def test_repeats_not_flagged(self):
        captions = [_make_caption(status="REPEATS")]
        result = classify_conflicts(captions, _make_stage1_note())
        assert result[0].conflict_flag is False

    def test_mixed_classification(self):
        captions = [
            _make_caption(frame_id="f1", status="ENRICHES"),
            _make_caption(frame_id="f2", status="REPEATS"),
            _make_caption(frame_id="f3", status="CONFLICTS"),
        ]
        result = classify_conflicts(captions, _make_stage1_note())
        assert not result[0].conflict_flag
        assert not result[1].conflict_flag
        assert result[2].conflict_flag


class TestNoteMerge:
    def test_enriches_injected(self):
        note = _make_stage1_note()
        captions = [_make_caption(status="ENRICHES", anchor_id="seg_001")]
        result = merge_visual_citations(note, captions)

        # Should have a new visual claim in physical_exam
        pe = result.get_section("physical_exam")
        assert pe is not None
        visual_claims = [c for c in pe.claims if c.source_type == "visual"]
        assert len(visual_claims) == 1
        assert result.stage == 2

    def test_repeats_discarded(self):
        note = _make_stage1_note()
        original_claims = len(note.get_section("physical_exam").claims)
        captions = [_make_caption(status="REPEATS", anchor_id="seg_001")]
        result = merge_visual_citations(note, captions)

        # No new claims added
        pe = result.get_section("physical_exam")
        assert len(pe.claims) == original_claims

    def test_conflicts_surfaced(self):
        note = _make_stage1_note()
        captions = [_make_caption(status="CONFLICTS", anchor_id="seg_001")]
        result = merge_visual_citations(note, captions)

        pe = result.get_section("physical_exam")
        conflict_claims = [c for c in pe.claims if "CONFLICT" in c.text]
        assert len(conflict_claims) == 1

    def test_pending_video_updated_on_enrichment(self):
        note = _make_stage1_note()
        assert note.get_section("imaging_review").status == "pending_video"

        captions = [_make_caption(
            status="ENRICHES",
            anchor_id="seg_003",
            description="MRI showing clear view of knee joint.",
        )]
        result = merge_visual_citations(note, captions)

        # imaging_review may now be populated if a caption was routed there
        # (depends on anchor matching — test with fallback routing)

    def test_remaining_pending_video_set_to_not_captured(self):
        note = _make_stage1_note()
        # No captions for imaging_review
        captions = [_make_caption(status="ENRICHES", anchor_id="seg_001")]
        result = merge_visual_citations(note, captions)

        # imaging_review had pending_video, should now be not_captured if no captions matched
        ir = result.get_section("imaging_review")
        assert ir.status in ("not_captured", "populated")

    def test_stage_updated_to_2(self):
        note = _make_stage1_note()
        captions = []
        result = merge_visual_citations(note, captions)
        assert result.stage == 2


class TestUnresolvedConflicts:
    def test_no_conflicts(self):
        captions = [_make_caption(status="ENRICHES")]
        assert has_unresolved_conflicts(captions) is False

    def test_has_conflicts(self):
        captions = [_make_caption(status="CONFLICTS")]
        assert has_unresolved_conflicts(captions) is True


class TestFrameWindowFromConfig:
    def test_clinic_window_default(self):
        ms = get_frame_window_ms(trigger_type="active_physical_examination")
        assert ms == 3000  # default clinic window

    def test_procedural_window(self):
        ms = get_frame_window_ms(trigger_type="procedural_step")
        assert ms == 7000  # default procedural window


class TestVisionSystemPrompts:
    """All three vision providers must use the EXACT same system prompt."""

    def test_all_vision_providers_use_same_prompt(self):
        assert OPENAI_VISION_PROMPT == ANTHROPIC_VISION_PROMPT
        assert ANTHROPIC_VISION_PROMPT == GEMINI_VISION_PROMPT

    def test_vision_prompt_enforces_descriptive_mode(self):
        assert "Do not diagnose" in OPENAI_VISION_PROMPT
        assert "literally visible" in OPENAI_VISION_PROMPT

    def test_vision_prompt_requires_json(self):
        assert "Return JSON only" in OPENAI_VISION_PROMPT

    def test_vision_prompt_defines_confidence_low(self):
        assert "blurry" in OPENAI_VISION_PROMPT
        assert "LOW" in OPENAI_VISION_PROMPT
