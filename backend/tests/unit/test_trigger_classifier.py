"""Tests for trigger classifier — keyword detection and suppression."""

import pytest

from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.transcription.trigger_classifier import (
    SUPPRESSION_PHRASES,
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
    def test_imaging_review_flagged(self):
        transcript = _make_transcript([
            "Looking at the MRI, there is no visible meniscal tear."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True
        assert result.segments[0].trigger_type is not None

    def test_physical_exam_flagged(self):
        transcript = _make_transcript([
            "There is tenderness on palpation at the medial joint line."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True

    def test_general_narration_not_flagged(self):
        transcript = _make_transcript([
            "The patient has been doing well since the last appointment."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False

    def test_gait_observation_flagged(self):
        transcript = _make_transcript([
            "The patient is walking with an antalgic gait."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True

    def test_wound_assessment_flagged(self):
        transcript = _make_transcript([
            "The wound edges appear well approximated."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True

    def test_visual_pointer_flagged(self):
        transcript = _make_transcript([
            "You can see right here that the tissue looks healthy."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is True


class TestSuppressionList:
    def test_suppression_phrases_not_empty(self):
        assert len(SUPPRESSION_PHRASES) > 0

    def test_last_visit_suppressed(self):
        transcript = _make_transcript([
            "At the last visit, the range of motion was limited."
        ])
        result = classify_triggers(transcript)
        # Even though "range of motion" is a trigger, "last visit" suppresses
        assert result.segments[0].is_visual_trigger is False

    def test_patient_reported_suppressed(self):
        transcript = _make_transcript([
            "The patient reported tenderness in the knee."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False

    def test_history_of_suppressed(self):
        transcript = _make_transcript([
            "History of palpation showed consistent findings."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False

    def test_previously_suppressed(self):
        transcript = _make_transcript([
            "Previously, the MRI showed a partial tear."
        ])
        result = classify_triggers(transcript)
        assert result.segments[0].is_visual_trigger is False


class TestTemplateKeywords:
    def test_template_keywords_used_when_available(self):
        transcript = _make_transcript([
            "There is tenderness on palpation at the medial joint line."
        ])
        result = classify_triggers(transcript, template=ORTHO_TEMPLATE)
        assert result.segments[0].is_visual_trigger is True

    def test_template_imaging_keywords(self):
        transcript = _make_transcript([
            "Looking at the X-ray, the fracture is well aligned."
        ])
        result = classify_triggers(transcript, template=ORTHO_TEMPLATE)
        assert result.segments[0].is_visual_trigger is True


class TestMixedSegments:
    def test_multiple_segments_classified_correctly(self):
        transcript = _make_transcript([
            "The patient presents with right knee pain.",
            "There is tenderness on palpation at the medial joint line.",
            "The patient reported this started two weeks ago.",
            "Looking at the MRI, there is no visible meniscal tear.",
            "We will continue conservative management.",
        ])
        result = classify_triggers(transcript)

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

    def test_empty_transcript(self):
        transcript = _make_transcript([])
        result = classify_triggers(transcript)
        assert len(result.segments) == 0

    def test_empty_template_keywords_falls_back_to_defaults(self):
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
        result = classify_triggers(transcript, template=empty_template)
        # Should use default keywords since template has empty lists
        assert result.segments[0].is_visual_trigger is True
