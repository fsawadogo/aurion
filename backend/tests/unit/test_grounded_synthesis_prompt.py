"""GS-1 (#543) — grounded note-gen system prompt, flag-gated (dark).

`resolve_base_system_prompt` swaps the note_generation base to the grounded
variant ONLY when feature_flags.grounded_synthesis_enabled is ON. OFF (the
default) is byte-identical to the descriptive prompt for every prompt id, so
live pilot output is unchanged until GS-9 sign-off.
"""

from __future__ import annotations

from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig
from app.modules.prompts import assembly
from app.modules.prompts.registry import PROMPTS
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_GROUNDED_SYSTEM_PROMPT,
    NOTE_GEN_SYSTEM_PROMPT,
)


def _cfg(on: bool) -> AppConfigSchema:
    return AppConfigSchema(feature_flags=FeatureFlagsConfig(grounded_synthesis_enabled=on))


def test_flag_off_note_gen_base_is_descriptive_byte_identical(monkeypatch):
    # AC-1: OFF → exactly the descriptive prompt.
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(False))
    assert assembly.resolve_base_system_prompt("note_generation") == NOTE_GEN_SYSTEM_PROMPT


def test_flag_on_note_gen_base_is_grounded(monkeypatch):
    # AC-2: ON → the grounded variant.
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))
    assert assembly.resolve_base_system_prompt("note_generation") == NOTE_GEN_GROUNDED_SYSTEM_PROMPT


def test_flag_on_does_not_touch_other_prompts(monkeypatch):
    # AC-3: only note_generation is swapped — vision/reconcile/preview stay literal.
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))
    for pid in ("vision_frame", "vision_reconcile"):
        if pid in PROMPTS:
            assert assembly.resolve_base_system_prompt(pid) == PROMPTS[pid].system_prompt


def test_grounded_prompt_requires_grounding_and_forbids_fabrication():
    # AC-4: the grounded prompt permits synthesis but mandates citation/grounding
    # and still bans fabrication; it differs from the descriptive base.
    p = NOTE_GEN_GROUNDED_SYSTEM_PROMPT.lower()
    assert "synthesiz" in p  # synthesis is permitted
    assert "cite" in p and "grounded" in p and "traceable" in p  # but grounded + cited
    assert "never fabricate" in p and "never invent a source" in p
    assert NOTE_GEN_GROUNDED_SYSTEM_PROMPT != NOTE_GEN_SYSTEM_PROMPT


def test_descriptive_base_unchanged():
    # The descriptive prompt still forbids interpretation (GS-4 changes the
    # validator, not this constant; the OFF path must remain descriptive).
    assert "Do not infer, interpret, diagnose" in NOTE_GEN_SYSTEM_PROMPT
