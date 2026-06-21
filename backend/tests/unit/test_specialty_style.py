"""Unit tests for the specialty style snippet (Tier 2 / item G)."""

from __future__ import annotations

import pytest

from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.note_gen.service import build_stage1_user_prompt
from app.modules.note_gen.specialty_style import get_specialty_style


class TestStyleLookup:
    @pytest.mark.parametrize(
        "key",
        [
            "orthopedic_surgery",
            "plastic_surgery",
            "musculoskeletal",
            "emergency_medicine",
            "general",
            "family_medicine",
            "internal_medicine",
            "pediatrics",
        ],
    )
    def test_every_specialty_has_a_snippet(self, key: str) -> None:
        snippet = get_specialty_style(key)
        assert snippet, f"{key} missing a style snippet"
        # Snippets stay concise — pointer, not textbook. The pilot
        # specialties (orthopedic_surgery, plastic_surgery) carry richer,
        # section-targeted guidance grounded in documentation standards, so
        # they get a higher cap; the rest stay terse until validated.
        cap = 1000 if key in ("orthopedic_surgery", "plastic_surgery") else 600
        assert len(snippet) < cap, (
            f"{key} snippet too long ({len(snippet)} chars, cap {cap})"
        )

    def test_unknown_specialty_returns_empty(self) -> None:
        assert get_specialty_style("does_not_exist") == ""
        assert get_specialty_style("") == ""


class TestSpecialtyStyleInPrompt:
    def _transcript(self) -> Transcript:
        return Transcript(
            session_id="s",
            provider_used="whisper",
            segments=[
                TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hello")
            ],
        )

    def test_orthopedic_style_renders_in_prompt(self) -> None:
        template = Template(
            key="orthopedic_surgery",
            display_name="Orthopedic Surgery",
            sections=[TemplateSection(id="cc", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        assert "STYLE GUIDANCE FOR Orthopedic Surgery" in prompt
        # Specific orthopedic pointer landed
        assert "medial joint line" in prompt or "ROM" in prompt or "modality" in prompt

    def test_pediatrics_style_attributes_caregiver(self) -> None:
        template = Template(
            key="pediatrics",
            display_name="Pediatrics",
            sections=[TemplateSection(id="cc", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        assert "Caregiver" in prompt or "caregiver" in prompt

    def test_unknown_specialty_omits_style_block(self) -> None:
        template = Template(
            key="experimental_dermatology",
            display_name="Dermatology",
            sections=[TemplateSection(id="cc", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        # No style block — base prompt still renders normally
        assert "STYLE GUIDANCE" not in prompt
        assert "Specialty: Dermatology" in prompt
        assert "TRANSCRIPT:" in prompt

    def test_style_block_precedes_transcript(self) -> None:
        """Order matters: the model sees style guidance BEFORE the
        transcript so it primes the extraction."""
        template = Template(
            key="emergency_medicine",
            display_name="Emergency Medicine",
            sections=[TemplateSection(id="cc", title="CC")],
        )
        prompt = build_stage1_user_prompt(self._transcript(), template)
        style_idx = prompt.find("STYLE GUIDANCE")
        transcript_idx = prompt.find("TRANSCRIPT:")
        assert 0 <= style_idx < transcript_idx
