"""Tests for trigger classifier — keyword detection and suppression."""

import pytest

from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.transcription.trigger_classifier import (
    SUPPRESSION_PHRASES,
    _build_keyword_map,
    classify_triggers,
)


def _make_transcript(texts: list[str]) -> Transcript:
    segments = [
        TranscriptSegment(
            id=f"seg_{i + 1:03d}",
            start_ms=i * 5000,
            end_ms=(i + 1) * 5000,
            text=text,
        )
        for i, text in enumerate(texts)
    ]
    return Transcript(session_id="test-session", provider_used="test", segments=segments)


ORTHO_TEMPLATE = Template(
    key="orthopedic_surgery",
    display_name="Orthopedic Surgery",
    sections=[
        TemplateSection(
            id="physical_exam",
            title="Physical Examination",
            required=True,
            visual_trigger_keywords=[
                "range of motion", "ROM", "flexion", "extension",
                "palpation", "tenderness", "guarding",
            ],
        ),
        TemplateSection(
            id="imaging_review",
            title="Imaging Review",
            required=True,
            visual_trigger_keywords=[
                "X-ray", "MRI", "CT", "looking at", "pulling up",
            ],
        ),
        TemplateSection(
            id="assessment",
            title="Assessment",
            required=True,
            visual_trigger_keywords=[],
        ),
    ],
)


class TestTriggerFlagging:
    @pytest.mark.asyncio
    async def test_imaging_review_flagged(self):
        transcript = _make_transcript([
            "Looking at the MRI, there is no visible meniscal tear."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True
        assert result.segments[0].trigger_type is not None

    @pytest.mark.asyncio
    async def test_physical_exam_flagged(self):
        transcript = _make_transcript([
            "There is tenderness on palpation at the medial joint line."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True

    @pytest.mark.asyncio
    async def test_general_narration_not_flagged(self):
        transcript = _make_transcript([
            "The patient has been doing well since the last appointment."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False

    @pytest.mark.asyncio
    async def test_gait_observation_flagged(self):
        transcript = _make_transcript([
            "The patient is walking with an antalgic gait."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True

    @pytest.mark.asyncio
    async def test_wound_assessment_flagged(self):
        transcript = _make_transcript([
            "The wound edges appear well approximated."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True

    @pytest.mark.asyncio
    async def test_visual_pointer_flagged(self):
        transcript = _make_transcript([
            "You can see right here that the tissue looks healthy."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True


class TestSuppressionList:
    def test_suppression_phrases_not_empty(self):
        assert len(SUPPRESSION_PHRASES) > 0

    @pytest.mark.asyncio
    async def test_last_visit_suppressed(self):
        transcript = _make_transcript([
            "At the last visit, the range of motion was limited."
        ])
        result = await classify_triggers(transcript)
        # Even though "range of motion" is a trigger, "last visit" suppresses
        assert result.segments[0].is_visual_trigger is False

    @pytest.mark.asyncio
    async def test_patient_reported_suppressed(self):
        transcript = _make_transcript([
            "The patient reported tenderness in the knee."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False

    @pytest.mark.asyncio
    async def test_history_of_suppressed(self):
        transcript = _make_transcript([
            "History of palpation showed consistent findings."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False

    @pytest.mark.asyncio
    async def test_previously_suppressed(self):
        transcript = _make_transcript([
            "Previously, the MRI showed a partial tear."
        ])
        result = await classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False


class TestTemplateKeywords:
    @pytest.mark.asyncio
    async def test_template_keywords_used_when_available(self):
        transcript = _make_transcript([
            "There is tenderness on palpation at the medial joint line."
        ])
        result = await classify_triggers(transcript, template=ORTHO_TEMPLATE)
        assert result.segments[0].is_visual_trigger is True

    @pytest.mark.asyncio
    async def test_template_imaging_keywords(self):
        transcript = _make_transcript([
            "Looking at the X-ray, the fracture is well aligned."
        ])
        result = await classify_triggers(transcript, template=ORTHO_TEMPLATE)
        assert result.segments[0].is_visual_trigger is True


class TestMixedSegments:
    @pytest.mark.asyncio
    async def test_multiple_segments_classified_correctly(self):
        transcript = _make_transcript([
            "The patient presents with right knee pain.",
            "There is tenderness on palpation at the medial joint line.",
            "The patient reported this started two weeks ago.",
            "Looking at the MRI, there is no visible meniscal tear.",
            "We will continue conservative management.",
        ])
        result = await classify_triggers(transcript)

        # Segment 0: general narration — not flagged
        assert result.segments[0].is_visual_trigger is False
        # Segment 1: physical exam — flagged
        assert result.segments[1].is_visual_trigger is True
        # Segment 2: "patient reported" — suppressed
        assert result.segments[2].is_visual_trigger is False
        # Segment 3: imaging review — flagged
        assert result.segments[3].is_visual_trigger is True
        # Segment 4: plan narration — not flagged
        assert result.segments[4].is_visual_trigger is False

    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        transcript = _make_transcript([])
        result = await classify_triggers(transcript)
        assert len(result.segments) == 0

    @pytest.mark.asyncio
    async def test_empty_template_keywords_falls_back_to_defaults(self):
        empty_template = Template(
            key="general",
            display_name="General",
            sections=[
                TemplateSection(id="physical_exam", title="Physical Exam", visual_trigger_keywords=[]),
            ],
        )
        transcript = _make_transcript([
            "There is tenderness on palpation."
        ])
        result = await classify_triggers(transcript, template=empty_template)
        # Should use default keywords since template has empty lists
        assert result.segments[0].is_visual_trigger is True


class TestKeywordMapMerging:
    """Sections sharing a trigger type must MERGE, not overwrite.

    `_section_id_to_trigger_type` is many-to-one — every id outside its small
    mapping collapses to `general_visual_pointer` — so the previous straight
    assignment dropped the keywords of every section but the last one sharing a
    type, and with them the frames those words would have triggered.
    """

    def test_sections_sharing_a_trigger_type_merge(self):
        # Two unmapped ids -> both collapse to general_visual_pointer.
        template = Template(
            key="letter",
            display_name="Letter",
            sections=[
                TemplateSection(
                    id="examination_findings",
                    title="Findings",
                    visual_trigger_keywords=["range of motion", "palpation"],
                ),
                TemplateSection(
                    id="investigations_reviewed",
                    title="Investigations",
                    visual_trigger_keywords=["x-ray", "mri"],
                ),
            ],
        )
        keyword_map = _build_keyword_map(template)
        bucket = keyword_map["general_visual_pointer"]
        # All four survive — pre-fix only the last section's two did.
        assert bucket == ["range of motion", "palpation", "x-ray", "mri"]

    def test_duplicate_keyword_across_sections_collapses(self):
        template = Template(
            key="dup",
            display_name="Dup",
            sections=[
                TemplateSection(
                    id="a", title="A", visual_trigger_keywords=["Looking At"]
                ),
                TemplateSection(
                    id="b", title="B", visual_trigger_keywords=["looking at", "wound"]
                ),
            ],
        )
        assert _build_keyword_map(template)["general_visual_pointer"] == [
            "looking at",
            "wound",
        ]

    def test_distinct_trigger_types_stay_separate(self):
        template = Template(
            key="ortho",
            display_name="Ortho",
            sections=[
                TemplateSection(
                    id="physical_exam", title="Exam", visual_trigger_keywords=["flexion"]
                ),
                TemplateSection(
                    id="imaging_review", title="Imaging", visual_trigger_keywords=["x-ray"]
                ),
            ],
        )
        keyword_map = _build_keyword_map(template)
        assert keyword_map["active_physical_examination"] == ["flexion"]
        assert keyword_map["live_imaging_review"] == ["x-ray"]

    @pytest.mark.asyncio
    async def test_merged_keywords_actually_flag_segments(self):
        """End-to-end: a word from the FIRST shared-type section still fires."""
        template = Template(
            key="letter",
            display_name="Letter",
            sections=[
                TemplateSection(
                    id="examination_findings",
                    title="Findings",
                    visual_trigger_keywords=["range of motion"],
                ),
                TemplateSection(
                    id="investigations_reviewed",
                    title="Investigations",
                    visual_trigger_keywords=["x-ray"],
                ),
            ],
        )
        transcript = _make_transcript(["Let me check your range of motion."])
        result = await classify_triggers(transcript, template=template)
        assert result.segments[0].is_visual_trigger is True
