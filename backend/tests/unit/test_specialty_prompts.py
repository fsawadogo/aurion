"""Specialty prompt-quality guards for the pilot specialties.

We enriched the orthopedic_surgery + plastic_surgery style guidance,
few-shot examples, and template metadata (grounded in clinical-documentation
standards). These tests lock in the two invariants that matter:

  1. DESCRIPTIVE MODE is preserved — the guidance and every worked-example
     claim describe what was said/seen and never use interpretive/diagnostic
     language (the model would learn to do the same from few-shot examples).
  2. The examples are STRUCTURALLY VALID — >=2 per specialty, every section
     id exists in the template, every claim is source-traceable.

The base system prompt is asserted untouched (test_note_gen.py owns the
detailed contract; here we just confirm the descriptive anchors survive).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.modules.note_gen.few_shot import _clear_cache, get_few_shot_examples
from app.modules.note_gen.specialty_style import get_specialty_style

# Pilot specialties carry 2 worked examples; wave-2 carry >=1 (they had none
# before). All five get the same descriptive-mode + validity guards.
PILOT = ["orthopedic_surgery", "plastic_surgery"]
WAVE2 = ["musculoskeletal", "emergency_medicine", "general"]
ENRICHED = PILOT + WAVE2
_MIN_EXAMPLES = {k: 2 for k in PILOT} | {k: 1 for k in WAVE2}

# At least one of these must appear — the guidance must frame itself as
# "describe/capture what was stated", not "decide/conclude".
_DESCRIPTIVE_ANCHORS = (
    "capture", "document", "describe", "as stated",
    "as the physician", "verbatim", "never infer", "never add",
)

# None of these may appear in the guidance OR any example claim text — they
# are the interpretive/diagnostic phrasings that cross descriptive mode.
# (Plain words like "diagnosis" are allowed — e.g. "working diagnosis as
# stated"; we forbid the interpretive PHRASES the model must never produce.)
_INTERPRETIVE_FORBIDDEN = (
    "consistent with",
    "suggestive of",
    "suggests",
    "indicative of",
    "concerning for",
    "rule out",
    "likely represents",
    "differential diagnosis",
    "raises concern",
    "appears to be",
    "you may diagnose",
    "you may interpret",
    "you can diagnose",
)

_TEMPLATES_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "app" / "modules" / "note_gen" / "templates"
)


def _load_template(key: str) -> dict:
    return json.loads((_TEMPLATES_DIR / f"{key}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", ENRICHED)
def test_style_guidance_is_descriptive(key: str) -> None:
    style = get_specialty_style(key)
    assert style.strip(), f"{key} has empty style guidance"
    low = style.lower()
    assert any(a in low for a in _DESCRIPTIVE_ANCHORS), (
        f"{key} style guidance lacks a descriptive anchor"
    )
    for bad in _INTERPRETIVE_FORBIDDEN:
        assert bad not in low, f"{key} style guidance uses interpretive phrase {bad!r}"


@pytest.mark.parametrize("key", ENRICHED)
def test_few_shot_examples_valid_and_descriptive(key: str) -> None:
    _clear_cache()
    examples = get_few_shot_examples(key)
    want = _MIN_EXAMPLES[key]
    assert len(examples) >= want, f"{key} should have >={want} worked example(s)"

    section_ids = {s["id"] for s in _load_template(key)["sections"]}
    for ex in examples:
        for sec in ex.get("note", {}).get("sections", []):
            assert sec["id"] in section_ids, (
                f"{key} example references unknown section {sec['id']!r}"
            )
            for claim in sec.get("claims", []):
                assert claim.get("source_id"), f"{key} claim missing source_id"
                assert claim.get("source_quote"), f"{key} claim missing source_quote"
                low = claim.get("text", "").lower()
                for bad in _INTERPRETIVE_FORBIDDEN:
                    assert bad not in low, (
                        f"{key} example claim uses interpretive phrase {bad!r}: "
                        f"{claim['text']!r}"
                    )


@pytest.mark.parametrize("key", ENRICHED)
def test_template_keywords_are_nonempty_strings(key: str) -> None:
    for sec in _load_template(key)["sections"]:
        for kw in sec.get("visual_trigger_keywords", []):
            assert isinstance(kw, str) and kw.strip(), (
                f"{key} section {sec['id']} has an empty/non-string keyword"
            )


def test_base_system_prompt_descriptive_anchors_intact() -> None:
    """The specialty layer must not have touched the base descriptive prompt."""
    from app.modules.providers.note_gen.shared import NOTE_GEN_SYSTEM_PROMPT

    low = NOTE_GEN_SYSTEM_PROMPT.lower()
    assert "do not infer" in low
    assert "do not conclude what it means" in low
