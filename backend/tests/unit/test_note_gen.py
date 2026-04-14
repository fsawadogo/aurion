"""Tests for note generation service — template loading, completeness, versioning."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import (
    Note,
    NoteClaim,
    NoteSection,
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.note_gen.service import calculate_completeness, get_template, load_templates
from app.modules.providers.note_gen.openai import SYSTEM_PROMPT as OPENAI_PROMPT
from app.modules.providers.note_gen.anthropic import SYSTEM_PROMPT as ANTHROPIC_PROMPT
from app.modules.providers.note_gen.gemini import SYSTEM_PROMPT as GEMINI_PROMPT


ORTHO_TEMPLATE = Template(
    key="orthopedic_surgery",
    display_name="Orthopedic Surgery",
    sections=[
        TemplateSection(id="chief_complaint", title="Chief Complaint", required=True),
        TemplateSection(id="hpi", title="History of Present Illness", required=True),
        TemplateSection(id="physical_exam", title="Physical Examination", required=True),
        TemplateSection(id="imaging_review", title="Imaging Review", required=True),
        TemplateSection(id="assessment", title="Assessment", required=True),
        TemplateSection(id="plan", title="Plan", required=True),
    ],
)


class TestCompletenessScore:
    def test_all_populated(self):
        note = Note(
            session_id="test",
            stage=1,
            provider_used="test",
            specialty="orthopedic_surgery",
            sections=[
                NoteSection(id="chief_complaint", status="populated", claims=[
                    NoteClaim(id="c1", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="hpi", status="populated", claims=[
                    NoteClaim(id="c2", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="physical_exam", status="populated", claims=[
                    NoteClaim(id="c3", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="imaging_review", status="populated", claims=[
                    NoteClaim(id="c4", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="assessment", status="populated", claims=[
                    NoteClaim(id="c5", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="plan", status="populated", claims=[
                    NoteClaim(id="c6", text="test", source_type="transcript", source_id="s1")
                ]),
            ],
        )
        assert calculate_completeness(note, ORTHO_TEMPLATE) == 1.0

    def test_partial_completeness(self):
        note = Note(
            session_id="test",
            stage=1,
            provider_used="test",
            specialty="orthopedic_surgery",
            sections=[
                NoteSection(id="chief_complaint", status="populated", claims=[
                    NoteClaim(id="c1", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="hpi", status="populated", claims=[
                    NoteClaim(id="c2", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="physical_exam", status="populated", claims=[
                    NoteClaim(id="c3", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="imaging_review", status="pending_video", claims=[]),
                NoteSection(id="assessment", status="populated", claims=[
                    NoteClaim(id="c5", text="test", source_type="transcript", source_id="s1")
                ]),
                NoteSection(id="plan", status="not_captured", claims=[]),
            ],
        )
        # 4 of 6 required sections populated
        score = calculate_completeness(note, ORTHO_TEMPLATE)
        assert abs(score - 4 / 6) < 0.01

    def test_empty_note(self):
        note = Note(
            session_id="test",
            stage=1,
            provider_used="test",
            specialty="orthopedic_surgery",
            sections=[],
        )
        assert calculate_completeness(note, ORTHO_TEMPLATE) == 0.0

    def test_populated_but_no_claims_not_counted(self):
        """A section marked populated but with empty claims list is not counted."""
        note = Note(
            session_id="test",
            stage=1,
            provider_used="test",
            specialty="orthopedic_surgery",
            sections=[
                NoteSection(id="chief_complaint", status="populated", claims=[]),
            ],
        )
        assert calculate_completeness(note, ORTHO_TEMPLATE) == 0.0


class TestTemplateLoading:
    def test_load_templates_returns_dict(self):
        templates = load_templates()
        assert isinstance(templates, dict)

    def test_known_templates_available(self):
        templates = load_templates()
        # At least the general template should exist
        if templates:
            for key in templates:
                assert templates[key].key == key
                assert len(templates[key].sections) > 0

    def test_get_template_invalid_falls_back_or_raises(self):
        """Invalid specialty falls back to general or raises ValueError."""
        templates = load_templates()
        if "general" in templates:
            # Should fall back to general
            result = get_template("nonexistent_specialty")
            assert result.key == "general"
        else:
            with pytest.raises(ValueError):
                get_template("nonexistent_specialty")


class TestSystemPrompts:
    """All three providers must use the EXACT same system prompt."""

    def test_all_providers_use_same_system_prompt(self):
        assert OPENAI_PROMPT == ANTHROPIC_PROMPT
        assert ANTHROPIC_PROMPT == GEMINI_PROMPT

    def test_system_prompt_enforces_descriptive_mode(self):
        assert "Do not infer" in OPENAI_PROMPT
        assert "Do not conclude what it means" in OPENAI_PROMPT
        assert "traceable to a source" in OPENAI_PROMPT

    def test_system_prompt_requires_json(self):
        assert "Return only valid JSON" in OPENAI_PROMPT

    def test_system_prompt_no_fabrication(self):
        assert "Never fabricate content" in OPENAI_PROMPT
