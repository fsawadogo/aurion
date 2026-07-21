"""TE-1 — note verbosity under template control (the detail level).

The other half of Marie's "trop verbeuse": TE-3/TE-4 fixed the frame-caption
clutter; this makes the TRANSCRIPT-completeness directive gradable. The safety
line the tests enforce: fewer WORDS on incidental material, never fewer
FINDINGS — and no level relaxes descriptive mode.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.providers.note_gen import shared
from app.modules.providers.note_gen.shared import (
    _DIRECTIVE_BRIEF,
    _DIRECTIVE_DETAILED,
    _DIRECTIVE_STANDARD,
    build_user_prompt,
)


def _transcript() -> Transcript:
    return Transcript(
        session_id=str(uuid.uuid4()),
        provider_used="whisper",
        segments=[TranscriptSegment(id="seg_0", start_ms=0, end_ms=10, text="hi")],
    )


def _template(detail_level=None) -> Template:
    return Template(
        key="general",
        display_name="General",
        sections=[TemplateSection(id="hpi", title="HPI")],
        detail_level=detail_level,
    )


def _flags(engine_on: bool):
    return SimpleNamespace(
        feature_flags=SimpleNamespace(template_engine_enabled=engine_on)
    )


def _prompt(detail_level, engine_on):
    with patch.object(shared, "get_config", return_value=_flags(engine_on)):
        return build_user_prompt(_transcript(), _template(detail_level), stage=1)


# ── AC-1 · flag OFF is byte-identical for every level ───────────────────────


def test_flag_off_is_byte_identical():
    """OFF → the exhaustive directive, regardless of detail_level. This is the
    rollout safety net: turning the engine off restores pre-TE-1 output."""
    for level in (None, "detailed", "standard", "brief"):
        prompt = _prompt(level, engine_on=False)
        assert _DIRECTIVE_DETAILED in prompt
        assert _DIRECTIVE_BRIEF not in prompt
        assert _DIRECTIVE_STANDARD not in prompt


# ── AC-2 · detailed / None reproduce today ──────────────────────────────────


def test_detailed_matches_today():
    """ON + None or detailed → the exact exhaustive directive."""
    for level in (None, "detailed"):
        assert _DIRECTIVE_DETAILED in _prompt(level, engine_on=True)


# ── AC-3 / AC-4 · brief and standard grade DOWN, but keep the essentials ─────


def test_brief_trims_minor_not_essential():
    prompt = _prompt("brief", engine_on=True)
    assert _DIRECTIVE_BRIEF in prompt
    assert _DIRECTIVE_DETAILED not in prompt
    # Genuinely graded down: brief < standard < detailed.
    assert len(_DIRECTIVE_BRIEF) < len(_DIRECTIVE_STANDARD) < len(_DIRECTIVE_DETAILED)
    # …but the essentials are still explicitly demanded, and dropping clinical
    # content is explicitly forbidden — brief != incomplete.
    lower = _DIRECTIVE_BRIEF.lower()
    for essential in ("finding", "medication", "plan"):
        assert essential in lower
    assert "never drop" in lower


def test_standard_is_between():
    prompt = _prompt("standard", engine_on=True)
    assert _DIRECTIVE_STANDARD in prompt
    assert _DIRECTIVE_DETAILED not in prompt
    assert _DIRECTIVE_BRIEF not in prompt
    lower = _DIRECTIVE_STANDARD.lower()
    for essential in ("finding", "medication", "plan"):
        assert essential in lower
    assert "never drop" in lower


# ── AC-7 · descriptive mode is untouched at every level ─────────────────────


def test_no_level_authorizes_inference():
    """No directive may introduce interpretive wording — this changes HOW MUCH
    is captured, never whether the model may interpret. If a future edit slips
    an interpretive verb into a directive, this fails."""
    banned = ("diagnose", "interpret", "infer", "conclude", "recommend treatment")
    for directive in (_DIRECTIVE_DETAILED, _DIRECTIVE_STANDARD, _DIRECTIVE_BRIEF):
        low = directive.lower()
        for word in banned:
            assert word not in low, f"{word!r} leaked into a directive"


def test_exactly_one_directive_per_prompt():
    """Whatever the level, the prompt carries exactly one completeness
    directive — never two, never zero."""
    for level, on in [
        (None, False), ("brief", True), ("standard", True), ("detailed", True),
    ]:
        prompt = _prompt(level, on)
        hits = sum(
            d in prompt
            for d in (_DIRECTIVE_DETAILED, _DIRECTIVE_STANDARD, _DIRECTIVE_BRIEF)
        )
        assert hits == 1
