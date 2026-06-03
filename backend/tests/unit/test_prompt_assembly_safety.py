"""Unit tests for AI Prompts B safety + selection (AI-PROMPTS-B,
replacement semantics).

Covers the parts that don't need a DB:
  * ``validate_user_prompt`` — empty / too-long / banned / missing
    descriptive-mode anchor / OK
  * ``select_active_prompt`` — synchronous selection between the
    physician's saved prompt and the registry default
  * Replacement invariant — when a user prompt is set, the base is
    NOT concatenated below it; the user prompt is returned alone

The integration suite covers the DB-bound paths (per-physician
isolation, PATCH/DELETE/audit). See
``backend/tests/integration/test_prompt_overrides.py``.
"""

from __future__ import annotations

import pytest

from app.modules.prompts import (
    BANNED_PHRASES,
    DESCRIPTIVE_ANCHORS_REQUIRED,
    PROMPTS,
    USER_PROMPT_MAX_LENGTH,
    ValidationCode,
    select_active_prompt,
    validate_user_prompt,
)

# A clinical-documentation prompt that contains BOTH required anchor
# groups + no banned phrases. Used as the canonical "passing" input by
# many tests below; centralised here so synonyms changes ripple.
_WELL_FORMED_USER_PROMPT = (
    "You are a clinical documentation assistant. "
    "Describe only what was directly captured during the encounter. "
    "Document the patient's complaints, observed physical findings, "
    "and any visible equipment. "
    "Do not interpret findings, do not diagnose, and do not infer "
    "clinical meaning beyond what is literally observed. "
    "Report what was said and what was seen, nothing more."
)


# ── validate_user_prompt: happy path ────────────────────────────────────────


def test_validate_user_prompt_accepts_well_formed_full_prompt() -> None:
    """A clinical-documentation prompt with both anchor groups + no
    banned phrases is accepted at full length."""
    result = validate_user_prompt(_WELL_FORMED_USER_PROMPT)
    assert result.code is ValidationCode.OK, result
    assert result.matched_phrase is None
    assert result.missing_anchor_group is None


def test_validate_user_prompt_accepts_long_well_formed_prompt() -> None:
    """A ~1500-character clinical-documentation prompt with both anchor
    groups passes — exercising the cap-side of the length check."""
    prompt = (
        _WELL_FORMED_USER_PROMPT
        + "\n\n"
        + (
            "Specific guidance for the upcoming visits: "
            "Carefully describe wound dimensions in millimeters where "
            "visible. Record the laterality of every observation. "
            "Document the patient's stated history verbatim where the "
            "audio captures it. "
        )
        * 8
    )
    assert 1000 < len(prompt) < USER_PROMPT_MAX_LENGTH
    result = validate_user_prompt(prompt)
    assert result.code is ValidationCode.OK, result


# ── validate_user_prompt: empty ─────────────────────────────────────────────


@pytest.mark.parametrize("blank", ["", "   ", "\n\n", "\t", "  \n  "])
def test_validate_user_prompt_rejects_empty(blank: str) -> None:
    result = validate_user_prompt(blank)
    assert result.code is ValidationCode.EMPTY
    assert result.matched_phrase is None
    assert result.missing_anchor_group is None


# ── validate_user_prompt: too long ──────────────────────────────────────────


def test_save_rejects_prompt_over_5000_chars() -> None:
    """One char past the cap fails. Cap is inclusive on the allowed
    side (i.e. exactly USER_PROMPT_MAX_LENGTH is OK)."""
    over = "a" * (USER_PROMPT_MAX_LENGTH + 1)
    result = validate_user_prompt(over)
    assert result.code is ValidationCode.TOO_LONG
    assert str(USER_PROMPT_MAX_LENGTH) in result.message


def test_validate_user_prompt_accepts_at_limit_with_anchors() -> None:
    """Exactly at the cap with valid anchors is OK — physicians
    shouldn't be punished for counting accurately."""
    # Build a string exactly USER_PROMPT_MAX_LENGTH chars that contains
    # the two anchor groups. Take the well-formed prompt as the seed
    # and pad with a neutral descriptive phrase up to the cap.
    seed = _WELL_FORMED_USER_PROMPT
    pad_unit = " describe more. "
    needed = USER_PROMPT_MAX_LENGTH - len(seed)
    padding = (pad_unit * (needed // len(pad_unit) + 1))[:needed]
    at_limit = seed + padding
    assert len(at_limit) == USER_PROMPT_MAX_LENGTH
    result = validate_user_prompt(at_limit)
    assert result.code is ValidationCode.OK, result


# ── validate_user_prompt: banlist ───────────────────────────────────────────


@pytest.mark.parametrize("banned", BANNED_PHRASES)
def test_validate_user_prompt_rejects_each_banned_phrase(banned: str) -> None:
    """One assertion per banlist entry — the lock-step invariant
    between BANNED_PHRASES and the unit tests. Removing an entry
    requires removing the corresponding parameterized case here (and a
    security review).

    The well-formed prompt would otherwise pass; injecting any banned
    phrase trips the gate before the anchor check, regardless of the
    surrounding anchor language.
    """
    poisoned = _WELL_FORMED_USER_PROMPT + f" Also: {banned}, please."
    result = validate_user_prompt(poisoned)
    assert result.code is ValidationCode.BANNED_PHRASE, banned
    assert result.matched_phrase == banned


def test_save_rejects_prompt_with_diagnose_the_patient_banned_phrase() -> None:
    """Targeted regression for one of the new direct-attack entries."""
    poisoned = _WELL_FORMED_USER_PROMPT + " Then diagnose the patient."
    result = validate_user_prompt(poisoned)
    assert result.code is ValidationCode.BANNED_PHRASE
    assert result.matched_phrase == "diagnose the patient"


def test_validate_user_prompt_banlist_is_case_insensitive() -> None:
    """Capitalising the attack must not bypass the matcher."""
    banned = BANNED_PHRASES[0]
    poisoned = _WELL_FORMED_USER_PROMPT + f" Hey {banned.upper()} please."
    result = validate_user_prompt(poisoned)
    assert result.code is ValidationCode.BANNED_PHRASE
    assert result.matched_phrase == banned


def test_validate_user_prompt_first_matched_phrase_is_reported() -> None:
    """When two banlist entries hit, the first one in BANNED_PHRASES
    wins. Stable error UX — same input always reports the same phrase."""
    poisoned = (
        _WELL_FORMED_USER_PROMPT
        + f" {BANNED_PHRASES[0]} and also {BANNED_PHRASES[1]}"
    )
    result = validate_user_prompt(poisoned)
    assert result.code is ValidationCode.BANNED_PHRASE
    assert result.matched_phrase == BANNED_PHRASES[0]


# ── validate_user_prompt: descriptive-mode anchors (NEW) ───────────────────


def test_save_rejects_prompt_without_descriptive_anchor_descriptive() -> None:
    """A prompt that omits the "describe / document / record / report"
    intent fails with MISSING_DESCRIPTIVE_ANCHOR pointing at group 0."""
    # Only the "do not interpret" anchor present; no descriptive verb.
    missing_describe = (
        "You are a clinical assistant. Do not interpret, do not "
        "diagnose, and do not infer clinical meaning."
    )
    result = validate_user_prompt(missing_describe)
    assert result.code is ValidationCode.MISSING_DESCRIPTIVE_ANCHOR
    assert result.missing_anchor_group == 0


def test_save_rejects_prompt_without_descriptive_anchor_no_interpret() -> None:
    """A prompt that omits the "do not interpret / diagnose / infer"
    instruction fails with MISSING_DESCRIPTIVE_ANCHOR pointing at
    group 1."""
    # Only the descriptive verb anchor present; no anti-interpretation
    # phrase.
    missing_no_interpret = (
        "You are a clinical assistant. Describe what was captured "
        "during the encounter. Document the patient's complaints "
        "verbatim. Record observed equipment positions."
    )
    result = validate_user_prompt(missing_no_interpret)
    assert result.code is ValidationCode.MISSING_DESCRIPTIVE_ANCHOR
    assert result.missing_anchor_group == 1


def test_validate_user_prompt_first_missing_group_is_reported() -> None:
    """When BOTH groups are missing, the first one (group 0) is the
    one reported. Stable UX, same as banlist short-circuit."""
    no_anchors = (
        "You are a clinical assistant. Be careful with the patient's "
        "personal information. Follow all standard policies."
    )
    result = validate_user_prompt(no_anchors)
    assert result.code is ValidationCode.MISSING_DESCRIPTIVE_ANCHOR
    assert result.missing_anchor_group == 0


@pytest.mark.parametrize("phrase", DESCRIPTIVE_ANCHORS_REQUIRED[0])
def test_each_group_0_phrase_satisfies_descriptive_anchor(phrase: str) -> None:
    """Lock-step: every synonym in group 0 should, on its own, satisfy
    the first anchor check. If a synonym is added to the tuple, this
    test must cover it."""
    # Build a prompt that satisfies group 1 (do not interpret) and uses
    # only the parametrised phrase for group 0.
    candidate = (
        f"You are a clinical assistant. Please {phrase} what you see. "
        "Do not interpret findings."
    )
    result = validate_user_prompt(candidate)
    assert result.code is ValidationCode.OK, (phrase, result)


@pytest.mark.parametrize("phrase", DESCRIPTIVE_ANCHORS_REQUIRED[1])
def test_each_group_1_phrase_satisfies_anti_interpret_anchor(
    phrase: str,
) -> None:
    """Same lock-step invariant for the anti-interpret group.

    The surrounding sentence is intentionally banlist-clean — phrasing
    like 'interpret the findings' is itself banned (it's a direct
    instruction to interpret), so this test wraps each anchor phrase
    with neutral context that won't trip the banlist regardless of the
    parametrised value.
    """
    candidate = f"Describe the encounter. {phrase} what you observe."
    result = validate_user_prompt(candidate)
    assert result.code is ValidationCode.OK, (phrase, result)


# ── select_active_prompt: replacement (NOT concatenation) ──────────────────


def test_select_active_prompt_no_user_prompt_returns_base() -> None:
    """No user prompt → exactly the base text, no separator, no
    extras. The base is the registry default fallback."""
    pid = "note_generation"
    out = select_active_prompt(pid, None)
    assert out == PROMPTS[pid].system_prompt


def test_select_active_prompt_empty_user_prompt_returns_base() -> None:
    """Empty-string user prompt falls back to base just like None.
    Defensive — the validator rejects empty inputs at save time, but
    the selector still has to handle a stale empty row gracefully."""
    pid = "note_generation"
    out = select_active_prompt(pid, "")
    assert out == PROMPTS[pid].system_prompt


def test_user_prompt_replaces_system_when_set() -> None:
    """When the user prompt is set, the active prompt is EXACTLY the
    user prompt — no base concatenation, no separator. This IS the
    replacement semantics in test form: the registry default is NOT
    present in the active prompt when the user prompt is set."""
    pid = "note_generation"
    user_prompt = _WELL_FORMED_USER_PROMPT
    out = select_active_prompt(pid, user_prompt)
    assert out == user_prompt
    # And critically — the registry default is NOT under it.
    base = PROMPTS[pid].system_prompt
    assert base not in out, (
        "Replacement semantics violated: the registry default was "
        "concatenated underneath the user prompt"
    )


def test_system_prompt_used_when_no_user_prompt() -> None:
    """When no user prompt is set, the active prompt is EXACTLY the
    registry default. This is the fallback half of the selection."""
    pid = "vision_frame"
    out = select_active_prompt(pid, None)
    assert out == PROMPTS[pid].system_prompt


# ── Replacement invariant — for EVERY catalog prompt ───────────────────────


@pytest.mark.parametrize("prompt_id", list(PROMPTS.keys()))
def test_user_prompt_replaces_base_for_every_prompt_id(prompt_id: str) -> None:
    """For any user prompt, the active prompt is EXACTLY that user
    prompt — for every catalog prompt. The registry default is the
    fallback only; replacement is never partial."""
    user_prompt = _WELL_FORMED_USER_PROMPT
    out = select_active_prompt(prompt_id, user_prompt)
    assert out == user_prompt, prompt_id


def test_select_active_prompt_unknown_prompt_id_raises() -> None:
    """Unknown prompt id is a programmer bug — surface loudly."""
    with pytest.raises(KeyError):
        select_active_prompt("not_a_real_prompt_id", "anything")
