"""scribe-2 (#622) — grounded-voice hardening.

(1) NOTE_GEN_GROUNDED_SYSTEM_PROMPT MANDATES a cited Assessment & Plan
    (MAY → MUST-when-cited-support), keeping the grounding floor + anti-over-reach.
(2) GROUNDED_BANNED_PHRASES rejects descriptive/thinning directives so an
    additive override can't steer grounded synthesis back to descriptive/thin.
(3) Grounded specialty-style is already selected in grounded mode (guard).

Flag OFF stays byte-identical.
"""

from __future__ import annotations

import pytest

from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig
from app.modules.note_gen import specialty_style as ss
from app.modules.prompts import safety
from app.modules.prompts.safety import ValidationCode, validate_user_prompt
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_GROUNDED_SYSTEM_PROMPT,
    NOTE_GEN_SYSTEM_PROMPT,
)


def _cfg(on: bool) -> AppConfigSchema:
    return AppConfigSchema(
        feature_flags=FeatureFlagsConfig(grounded_synthesis_enabled=on)
    )


# ── (1) grounded prompt mandates a cited A&P, grounding floor intact ──────────


def test_grounded_prompt_mandates_synthesis():
    low = NOTE_GEN_GROUNDED_SYSTEM_PROMPT.lower()
    assert "must synthesize" in low  # mandate…
    assert "may synthesize the assessment" not in low  # …not the old permissive wording
    # grounding floor tokens preserved (mirrors AC-4 of test_grounded_synthesis_prompt)
    for tok in (
        "synthesiz",
        "cite",
        "grounded",
        "traceable",
        "never fabricate",
        "never invent a source",
    ):
        assert tok in low, tok
    # anti-over-reach clause for thin encounters
    assert "too thin" in low


def test_descriptive_prompt_untouched():
    # flag-OFF constant must stay descriptive (not mutated by scribe-2)
    assert "Do not infer, interpret, diagnose" in NOTE_GEN_SYSTEM_PROMPT
    assert "must synthesize" not in NOTE_GEN_SYSTEM_PROMPT.lower()


# ── (2) grounded banlist rejects descriptive/thinning overrides ──────────────

_SUPPRESSIVE = [
    "Document and cite each finding. Do not synthesize an assessment.",
    "Cite every claim. Do not diagnose.",
    "Ground each statement. Descriptive mode only.",
    "Cite sources. Summarize to a handful of claims.",
    "Cite each finding. Omit the assessment.",
    "Ground every claim. Documentation only.",
]


@pytest.mark.parametrize("text", _SUPPRESSIVE)
def test_grounded_banlist_rejects_suppressive_override(monkeypatch, text):
    monkeypatch.setattr(safety, "get_config", lambda: _cfg(True))
    assert validate_user_prompt(text).code == ValidationCode.BANNED_PHRASE


def test_grounded_legit_prompt_still_passes(monkeypatch):
    monkeypatch.setattr(safety, "get_config", lambda: _cfg(True))
    ok = (
        "Document the encounter and synthesize an Assessment and Plan. Make a "
        "diagnosis and recommend treatment when supported, but every claim MUST "
        "be grounded and traceable — cite the source id for each. Never fabricate."
    )
    assert validate_user_prompt(ok).code == ValidationCode.OK


def test_flag_off_unaffected_by_grounded_additions(monkeypatch):
    # The new phrases live ONLY in GROUNDED_BANNED_PHRASES; the descriptive path
    # (flag OFF) is unchanged.
    monkeypatch.setattr(safety, "get_config", lambda: _cfg(False))
    descriptive = (
        "Describe only what was captured. Do not interpret, diagnose, or infer."
    )
    assert validate_user_prompt(descriptive).code == ValidationCode.OK


# ── (3) grounded mode already selects the grounded specialty style (guard) ────


def test_grounded_specialty_style_is_grounded(monkeypatch):
    monkeypatch.setattr(ss, "get_config", lambda: _cfg(True))
    s = ss.get_specialty_style("orthopedic_surgery").lower()
    assert "synthesize" in s and "cite" in s
    assert "never interpret" not in s


def test_specialty_style_off_is_descriptive(monkeypatch):
    monkeypatch.setattr(ss, "get_config", lambda: _cfg(False))
    s = ss.get_specialty_style("orthopedic_surgery")
    assert s == ss._STYLE["orthopedic_surgery"]
