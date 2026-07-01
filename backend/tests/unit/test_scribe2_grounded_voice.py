"""scribe-2 (#622) — grounded-voice hardening.

The grounded note-gen prompt MANDATES a cited Assessment & Plan (synthesis is
the DEFAULT; declining is a narrow exception), while keeping the grounding floor.
Grounded specialty-style is already selected in grounded mode (guard test).

The descriptive/thinning BANLIST idea was DROPPED after the #629 review:
substring bans false-matched legitimate grounded prompts (grounding caveats
legitimately say "do not synthesize beyond the sources", "documentation only
where evidence exists", …), and scribe-1's always-on grounded boundary is the
real guarantee that an override cannot strip grounding.

Flag OFF stays byte-identical.
"""

from __future__ import annotations

from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig
from app.modules.note_gen import specialty_style as ss
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_GROUNDED_SYSTEM_PROMPT,
    NOTE_GEN_SYSTEM_PROMPT,
)


def _cfg(on: bool) -> AppConfigSchema:
    return AppConfigSchema(
        feature_flags=FeatureFlagsConfig(grounded_synthesis_enabled=on)
    )


# ── grounded prompt mandates a cited A&P by default, grounding floor intact ───


def test_grounded_prompt_mandates_synthesis():
    low = NOTE_GEN_GROUNDED_SYSTEM_PROMPT.lower()
    # the MUST is bound to synthesizing the Assessment & Plan, and it is the default
    assert "must synthesize a cited assessment & plan" in low
    assert "by default" in low
    assert "may synthesize the assessment" not in low  # old permissive wording gone
    # declining is a NARROW exception, not a co-equal branch
    assert "only when" in low
    # grounding-floor tokens preserved
    for tok in (
        "synthesiz",
        "cite",
        "grounded",
        "traceable",
        "never fabricate",
        "never invent a source",
    ):
        assert tok in low, tok


def test_descriptive_prompt_untouched():
    # flag-OFF constant stays descriptive (not mutated by scribe-2)
    assert "Do not infer, interpret, diagnose" in NOTE_GEN_SYSTEM_PROMPT
    assert "must synthesize" not in NOTE_GEN_SYSTEM_PROMPT.lower()


# ── grounded mode already selects the grounded specialty style (guard) ────────


def test_grounded_specialty_style_is_grounded(monkeypatch):
    monkeypatch.setattr(ss, "get_config", lambda: _cfg(True))
    s = ss.get_specialty_style("orthopedic_surgery").lower()
    assert "synthesize" in s and "cite" in s
    assert "never interpret" not in s


def test_specialty_style_off_is_descriptive(monkeypatch):
    monkeypatch.setattr(ss, "get_config", lambda: _cfg(False))
    assert (
        ss.get_specialty_style("orthopedic_surgery")
        == ss._STYLE["orthopedic_surgery"]
    )
