"""Unit tests for AI Prompts B safety + assembly (AI-PROMPTS-B).

Covers the parts that don't need a DB:
  * ``validate_overlay`` — empty / too-long / banned-phrase / OK
  * ``assemble_preview`` — synchronous join, base immutability invariant
  * ``OVERLAY_SEPARATOR`` — present when overlay is set, absent otherwise

The integration suite covers the DB-bound paths (per-physician
isolation, PATCH/DELETE/audit). See
``backend/tests/integration/test_prompt_overrides.py``.
"""

from __future__ import annotations

import pytest

from app.modules.prompts import (
    BANNED_PHRASES,
    OVERLAY_MAX_LENGTH,
    OVERLAY_SEPARATOR,
    PROMPTS,
    ValidationCode,
    assemble_preview,
    validate_overlay,
)

# ── validate_overlay: happy path ────────────────────────────────────────────


@pytest.mark.parametrize(
    "good_overlay",
    [
        "Always note bilateral comparison when applicable.",
        "Use millimeters not centimeters for wound measurements.",
        "Prefer 'observed' over 'noted' in physical exam claims.",
        "Document the patient's preferred name in the chief complaint.",
        # Single short word — overlay is structurally a free-text field.
        "Brief.",
    ],
)
def test_validate_overlay_accepts_well_formed_text(good_overlay: str) -> None:
    result = validate_overlay(good_overlay)
    assert result.code is ValidationCode.OK, result
    assert result.matched_phrase is None


# ── validate_overlay: empty ─────────────────────────────────────────────────


@pytest.mark.parametrize("blank", ["", "   ", "\n\n", "\t", "  \n  "])
def test_validate_overlay_rejects_empty(blank: str) -> None:
    result = validate_overlay(blank)
    assert result.code is ValidationCode.EMPTY
    assert result.matched_phrase is None


# ── validate_overlay: too long ──────────────────────────────────────────────


def test_validate_overlay_rejects_over_limit() -> None:
    """One char past the cap fails — the cap is inclusive on the
    allowed side."""
    over = "a" * (OVERLAY_MAX_LENGTH + 1)
    result = validate_overlay(over)
    assert result.code is ValidationCode.TOO_LONG
    assert str(OVERLAY_MAX_LENGTH) in result.message


def test_validate_overlay_accepts_at_limit() -> None:
    """Exactly at the cap is OK — physicians shouldn't be punished for
    counting accurately."""
    at_limit = "a" * OVERLAY_MAX_LENGTH
    result = validate_overlay(at_limit)
    assert result.code is ValidationCode.OK


# ── validate_overlay: banlist ───────────────────────────────────────────────


@pytest.mark.parametrize("banned", BANNED_PHRASES)
def test_validate_overlay_rejects_each_banned_phrase(banned: str) -> None:
    """One assertion per banlist entry — the lock-step invariant
    between BANNED_PHRASES and the unit tests. Removing an entry
    requires removing the corresponding parameterized case here
    (and a security review)."""
    # Wrap in some plausible physician phrasing so we exercise the
    # substring-match path, not just exact equality.
    overlay = f"Per my preference: {banned}, then describe normally."
    result = validate_overlay(overlay)
    assert result.code is ValidationCode.BANNED_PHRASE, banned
    assert result.matched_phrase == banned


def test_validate_overlay_banlist_is_case_insensitive() -> None:
    """Capitalising the attack must not bypass the matcher."""
    # Pick the first entry and shout it.
    banned = BANNED_PHRASES[0]
    overlay = f"Hey {banned.upper()} please"
    result = validate_overlay(overlay)
    assert result.code is ValidationCode.BANNED_PHRASE
    assert result.matched_phrase == banned


def test_validate_overlay_first_matched_phrase_is_reported() -> None:
    """When two banlist entries hit, the first one in BANNED_PHRASES
    wins. Stable error UX — same input always reports the same phrase."""
    # Construct an overlay containing the first two entries.
    overlay = (
        f"{BANNED_PHRASES[0]} and also {BANNED_PHRASES[1]}"
    )
    result = validate_overlay(overlay)
    assert result.code is ValidationCode.BANNED_PHRASE
    assert result.matched_phrase == BANNED_PHRASES[0]


# ── assemble_preview: base + overlay join ──────────────────────────────────


def test_assemble_preview_no_overlay_returns_base() -> None:
    """No overlay → exactly the base text, no separator, no extras."""
    pid = "note_generation"
    out = assemble_preview(pid, None)
    assert out == PROMPTS[pid].system_prompt


def test_assemble_preview_empty_overlay_returns_base() -> None:
    """Empty string overlay falls back to base just like None."""
    pid = "note_generation"
    out = assemble_preview(pid, "")
    assert out == PROMPTS[pid].system_prompt


def test_assemble_preview_with_overlay_appends_below_separator() -> None:
    pid = "note_generation"
    overlay = "Always note bilateral comparison when applicable."
    out = assemble_preview(pid, overlay)
    base = PROMPTS[pid].system_prompt
    assert out.startswith(base), (
        "Assembled prompt must start with the base text exactly — "
        "base is the descriptive-mode safety boundary"
    )
    assert OVERLAY_SEPARATOR in out
    assert overlay in out


# ── Base immutability invariant ─────────────────────────────────────────────


@pytest.mark.parametrize("prompt_id", list(PROMPTS.keys()))
def test_assembled_prompt_preserves_base(prompt_id: str) -> None:
    """For any overlay, the base text is exactly present at the start
    of the assembled prompt — for every catalog prompt. This IS the
    CLAUDE.md descriptive-mode invariant in test form: no overlay can
    ever mutate or shadow the base."""
    overlay = "Use clinical-neutral phrasing where possible."
    out = assemble_preview(prompt_id, overlay)
    base = PROMPTS[prompt_id].system_prompt
    assert out.startswith(base), prompt_id
    # And the separator is between them, not embedded inside the base.
    assert out[len(base) :].startswith(f"\n\n{OVERLAY_SEPARATOR}\n")


def test_assemble_preview_unknown_prompt_id_raises() -> None:
    """Unknown prompt id is a programmer bug — surface loudly."""
    with pytest.raises(KeyError):
        assemble_preview("not_a_real_prompt_id", "anything")
