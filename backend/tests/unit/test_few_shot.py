"""Unit tests for the few-shot examples loader + prompt rendering
(Tier 2 / item E)."""

from __future__ import annotations

import json

import pytest

from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.note_gen.few_shot import (
    _clear_cache,
    get_few_shot_examples,
    render_examples_block,
)
from app.modules.note_gen.service import (
    _clear_template_cache,
    build_stage1_user_prompt,
    load_templates,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    _clear_cache()
    _clear_template_cache()


# ── Loader ────────────────────────────────────────────────────────────


class TestLoader:
    def test_loads_shipped_orthopedic_example(self) -> None:
        examples = get_few_shot_examples("orthopedic_surgery")
        assert len(examples) >= 1
        first = examples[0]
        assert "transcript" in first
        assert "note" in first
        # The example never uses interpretive language (descriptive
        # mode is non-negotiable, including in examples).
        note_json = json.dumps(first["note"])
        for forbidden in [
            "consistent with",
            "suggests ",
            "consider ",
            "rule out",
            "differential",
        ]:
            assert forbidden not in note_json.lower(), (
                f"example contains interpretive phrase: {forbidden!r}"
            )

    def test_loads_shipped_pediatrics_example(self) -> None:
        examples = get_few_shot_examples("pediatrics")
        assert len(examples) >= 1
        # Caregiver attribution must be present (pediatric style)
        note_json = json.dumps(examples[0]["note"])
        assert "Caregiver" in note_json

    def test_loads_shipped_plastic_example(self) -> None:
        examples = get_few_shot_examples("plastic_surgery")
        assert len(examples) >= 1
        # Wound dimensions present (plastic style)
        note_json = json.dumps(examples[0]["note"])
        assert "cm" in note_json or "6 × 3" in note_json or "6 by 3" in note_json

    def test_missing_specialty_returns_empty(self) -> None:
        assert get_few_shot_examples("does_not_exist") == []

    def test_cache_returns_same_object_on_second_call(self) -> None:
        first = get_few_shot_examples("orthopedic_surgery")
        second = get_few_shot_examples("orthopedic_surgery")
        # Same list instance — proves cache hit, no re-read of disk
        assert first is second


# ── Renderer ──────────────────────────────────────────────────────────


class TestRender:
    def test_empty_input_renders_empty_string(self) -> None:
        assert render_examples_block([]) == ""

    def test_render_includes_transcript_and_ideal_note(self) -> None:
        block = render_examples_block([{
            "description": "test case",
            "transcript": [
                {"id": "seg_A", "start_ms": 0, "end_ms": 1000, "text": "hello"}
            ],
            "note": {"sections": [{"id": "cc", "status": "populated", "claims": []}]},
        }])
        assert "EXAMPLE 1 (test case):" in block
        assert "[seg_A] (0ms–1000ms): hello" in block
        assert "IDEAL NOTE:" in block
        # The note JSON is pretty-printed (model reads structure easier)
        assert '"sections":' in block


# ── Integration with build_stage1_user_prompt ─────────────────────────


class TestPromptIntegration:
    def _transcript(self) -> Transcript:
        return Transcript(
            session_id="s",
            provider_used="whisper",
            segments=[
                TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hi")
            ],
        )

    def test_orthopedic_prompt_includes_worked_example(self) -> None:
        template = Template(
            key="orthopedic_surgery",
            display_name="Orthopedic Surgery",
            sections=[TemplateSection(id="chief_complaint", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        assert "WORKED EXAMPLES" in prompt
        assert "EXAMPLE 1" in prompt

    def test_examples_block_precedes_real_transcript(self) -> None:
        template = Template(
            key="pediatrics",
            display_name="Pediatrics",
            sections=[TemplateSection(id="cc", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        ex_idx = prompt.find("WORKED EXAMPLES")
        # The REAL transcript block starts after the examples
        # (the marker "TRANSCRIPT:" appears in both examples and the
        # real prompt; we want the LAST one to be after the examples block).
        real_transcript_idx = prompt.rfind("TRANSCRIPT:")
        assert 0 <= ex_idx < real_transcript_idx

    def test_unknown_specialty_omits_examples_block(self) -> None:
        template = Template(
            key="experimental_dermatology",
            display_name="Dermatology",
            sections=[TemplateSection(id="cc", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        assert "WORKED EXAMPLES" not in prompt
        # Base prompt still functional
        assert "TRANSCRIPT:" in prompt


# ── load_templates regression: examples files don't pollute the template registry ──


class TestTemplateLoaderIgnoresExamples:
    def test_examples_files_not_loaded_as_templates(self) -> None:
        templates = load_templates()
        # The 8 real templates are loaded, but the *.examples.json
        # siblings must not appear as Template instances (they'd fail
        # the Template Pydantic shape).
        assert "orthopedic_surgery" in templates
        assert "pediatrics" in templates
        assert "plastic_surgery" in templates
        # No key looks like an "examples" key
        for k in templates:
            assert "examples" not in k
