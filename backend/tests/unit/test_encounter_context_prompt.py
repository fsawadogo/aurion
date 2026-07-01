"""Unit tests for the ENCOUNTER CONTEXT block in the live note prompt.

Note-Options phase 2: the clinician-provided encounter context (e.g. the visit
expanded from "breast augmentation" to also cover liposuction) is now injected
into the LIVE provider prompt (``shared.build_user_prompt``) so a multi-topic /
under-narrated encounter is documented under the right sections. Descriptive
mode is preserved — the block is framing, NOT a captured finding, and the
prompt says so explicitly so the model never mints a claim solely from it.
"""

from __future__ import annotations

from app.core.types import (
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.providers.note_gen.shared import build_user_prompt


def _transcript() -> Transcript:
    return Transcript(
        session_id="s",
        provider_used="whisper",
        segments=[
            TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hi")
        ],
    )


def _template() -> Template:
    return Template(
        key="plastic_surgery",
        display_name="Plastic Surgery",
        sections=[TemplateSection(id="cc", title="CC")],
    )


def test_context_block_injected_when_present() -> None:
    prompt = build_user_prompt(
        _transcript(), _template(), stage=1,
        encounter_context="Breast augmentation consult; also discussing liposuction",
    )
    assert "ENCOUNTER CONTEXT" in prompt
    assert "liposuction" in prompt


def test_context_block_is_descriptive_mode_safe() -> None:
    """The framing must explicitly forbid minting a claim from the context —
    the descriptive-mode guardrail that keeps this from becoming fabrication."""
    prompt = build_user_prompt(
        _transcript(), _template(), stage=1,
        encounter_context="Breast aug; also lipo",
    )
    lowered = prompt.lower()
    assert "not itself a captured finding" in lowered
    assert "never create a claim solely from" in lowered


def test_no_context_omits_block() -> None:
    prompt = build_user_prompt(_transcript(), _template(), stage=1)
    assert "ENCOUNTER CONTEXT" not in prompt


def test_blank_context_omits_block() -> None:
    for blank in ("", "   ", "\n\t "):
        prompt = build_user_prompt(
            _transcript(), _template(), stage=1, encounter_context=blank
        )
        assert "ENCOUNTER CONTEXT" not in prompt
