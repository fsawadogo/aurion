"""Structural safety validation for per-physician user prompts.

Phase B of AI Prompts Transparency, **replacement** semantics.

A clinician can save a full standalone system prompt that REPLACES the
registry's base prompt for their own sessions. When they do, the LLM
receives their text *alone* — the base prompt is no longer concatenated
underneath. That makes this validator the single thing standing between
a physician's free-text input and the descriptive-mode safety boundary
locked in CLAUDE.md.

The check is **structural only** — no LLM call, no semantic judgement —
because:
  1. An LLM gate would add ~2s of latency to every save and cost money.
  2. False positives from a learned judge are opaque; a substring
     banlist + an anchor-presence check let us echo back exactly what
     tripped or what is missing.
  3. Substring matching catches the classes of attack the pilot
     audience can plausibly execute (the physician is also the safety
     reviewer of their own prompt at edit time).

Three gates run in order:
  1. Length cap (5000 chars). Raised from the v1 overlay cap of 1000:
     this is now a *full* system prompt, not an appended preference.
  2. Banlist of phrases that would actively disable descriptive mode.
     Maintained as a single tuple — add an entry = ship it everywhere.
  3. Required descriptive-mode anchors. The saved prompt MUST contain
     language equivalent to "describe / document / record what is
     observed" AND "do not interpret / diagnose / infer". Without that,
     replacement would silently strip the descriptive-mode boundary.

DRY / SRP — one function, one banlist, one anchor-groups tuple, one
result shape. Each new check = one new tuple entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# ── Limits ──────────────────────────────────────────────────────────────────

#: Hard cap on a saved user prompt's length, in characters. Raised from
#: the v1 overlay cap of 1000 because the saved text is now a full
#: standalone system prompt, not an appended preference paragraph. 5000
#: comfortably fits the longest base prompt in the registry (note_gen
#: is ~1.4k chars) with room for clinician customisation, while still
#: being small enough that a malicious payload can't smuggle in a giant
#: instruction wall the physician didn't review.
USER_PROMPT_MAX_LENGTH: Final[int] = 5000


# ── Banlist ─────────────────────────────────────────────────────────────────
#
# Phrases a saved user prompt MUST NOT contain. Match is case-insensitive
# substring — a longer/embedded match still trips. Each entry is the
# shortest unambiguous form of the attack so the matcher catches common
# variants without an explosion of near-duplicates.
#
# Maintenance: add a new entry as a single tuple line with an inline
# comment explaining what attack it shuts down. Removing an entry
# requires explicit security review (and a corresponding test removal
# below — the unit tests assert one-rejection-per-entry so the banlist
# and tests stay in lock-step).
#
# CLAUDE.md grounding: every entry below targets a phrase that would
# weaken the descriptive-mode boundary. Under replacement semantics
# (the saved prompt fully replaces the base) letting any of these slip
# would let the LLM cross the line from documentation into
# interpretation — there is no longer a base prompt below to recover
# from a compromised user prompt.

BANNED_PHRASES: Final[tuple[str, ...]] = (
    # Direct prompt-injection / instruction-override vectors.
    "ignore previous instructions",
    "ignore the above",
    "disregard prior rules",
    "system prompt override",
    "your new role is",
    "override the system",
    "replace the system prompt",
    # Role-flip attempts — turning the documentation assistant into a
    # diagnostic / interpretive one.
    "you may diagnose",
    "you can diagnose",
    "you may interpret",
    "you can now interpret",
    "act as a diagnostic",
    # Direct repeal of descriptive mode itself.
    "stop being descriptive",
    "no longer descriptive",
    "ignore the descriptive",
    # Verb-form attacks asking for diagnosis / interpretation / treatment
    # recommendations directly. Caught even when wrapped in physician
    # phrasing (the matcher is substring-based).
    "diagnose the patient",
    "make a diagnosis",
    "recommend treatment",
    "suggest treatment",
    "interpret the findings",
)


# ── Descriptive-mode anchors (NEW under replacement semantics) ──────────────
#
# Because the saved prompt now REPLACES the registry base, the
# descriptive-mode boundary lives entirely inside the physician's text.
# This tuple defines the conceptual groups the saved prompt MUST hit at
# least one phrase from. The matcher is the same case-insensitive
# substring scan the banlist uses.
#
# Each inner tuple is one conceptual group. ALL groups must match (i.e.
# at least one phrase per group). The order matters for failure
# reporting: the first missing group's index is what the error returns,
# so the UI can render the right localised hint. Don't reorder without
# updating the i18n keys + tests.
#
# Maintenance: add synonyms to an existing group when physicians get
# tripped up on legitimate phrasing; add a new group only if a new
# conceptual axis of the descriptive-mode boundary needs guarding.

DESCRIPTIVE_ANCHORS_REQUIRED: Final[tuple[tuple[str, ...], ...]] = (
    # Group 0 — descriptive intent. The prompt must instruct the LLM to
    # describe / document / record what was observed. Common variants
    # included; "report what" catches "report what was said / heard /
    # captured" which note-gen-style prompts use.
    (
        "describe",
        "document",
        "record",
        "report what",
    ),
    # Group 1 — explicit prohibition on interpretation / diagnosis /
    # inference. The prompt must instruct the LLM NOT to interpret,
    # diagnose, or infer. Synonyms cover both imperative and gerund
    # phrasings ("do not interpret" / "without interpreting") so a
    # well-written clinical-documentation prompt always passes.
    (
        "do not interpret",
        "do not diagnose",
        "do not infer",
        "no interpretation",
        "no diagnosis",
        "not interpret",
        "not diagnose",
        "without interpreting",
        "without diagnosing",
    ),
)


# ── Result shape ────────────────────────────────────────────────────────────


class ValidationCode(StrEnum):
    """Outcome category for :func:`validate_user_prompt`.

    ``StrEnum`` so the API layer can serialize the code verbatim into
    the 400 response body — the frontend uses the code to pick the
    right localised error string, the matched_phrase to highlight which
    banned phrase tripped, and the missing_anchor_group to name the
    group whose presence the saved prompt is missing.
    """

    OK = "ok"
    TOO_LONG = "too_long"
    BANNED_PHRASE = "banned_phrase"
    EMPTY = "empty"
    MISSING_DESCRIPTIVE_ANCHOR = "missing_descriptive_anchor"


@dataclass(frozen=True)
class ValidationResult:
    """Structural validation outcome.

    ``message`` is safe to surface to the physician — no PHI, no
    secrets. ``matched_phrase`` is the exact banned phrase the input
    contained when ``code == BANNED_PHRASE``; safe to echo back so the
    physician knows which word tripped the gate. ``missing_anchor_group``
    is the index into :data:`DESCRIPTIVE_ANCHORS_REQUIRED` for the
    group whose anchor phrases were all missing when
    ``code == MISSING_DESCRIPTIVE_ANCHOR`` — the UI uses it to render
    the right localised hint (e.g. "must include language like
    'describe' / 'document' / 'record'").
    """

    code: ValidationCode
    message: str
    matched_phrase: str | None = None
    missing_anchor_group: int | None = None


# ── Public API ──────────────────────────────────────────────────────────────


def validate_user_prompt(text: str) -> ValidationResult:
    """Structural safety check for a physician-supplied user prompt.

    Returns OK or a specific failure code. The matcher strips
    surrounding whitespace, then runs the gates in this order:

      1. Empty → ``EMPTY``
      2. Length > ``USER_PROMPT_MAX_LENGTH`` chars → ``TOO_LONG``
      3. Any ``BANNED_PHRASES`` entry appears (case-insensitive
         substring) → ``BANNED_PHRASE`` with ``matched_phrase`` set
      4. Any group in ``DESCRIPTIVE_ANCHORS_REQUIRED`` has zero matches
         → ``MISSING_DESCRIPTIVE_ANCHOR`` with ``missing_anchor_group``
         set to the first failing group's index
      5. Otherwise → ``OK``

    Why this order?
      * Empty is detected before length so a blank input gets the
        cleanest possible feedback.
      * Length is checked before the banlist so a 10k-character paste
        doesn't pay the substring-scan cost.
      * Banlist runs before anchor checks because a banned phrase is
        an *active* attack while a missing anchor is a *missing*
        safety token — telling the physician about the active attack
        first is the more useful UX.
      * Anchor checks are last so the saved prompt only reaches
        upsert when banlist-clean + length-clean — the missing-anchor
        message is actionable ("add 'do not interpret' somewhere")
        rather than buried under other failures.

    Failure reporting is short-circuit at each gate; the first matching
    banned phrase / first missing anchor group is the one returned.
    Stable error UX: same input always produces the same response.
    """
    stripped = text.strip() if text else ""
    if not stripped:
        return ValidationResult(
            code=ValidationCode.EMPTY,
            message=(
                "Your prompt is empty. Either add a full clinical-"
                "documentation prompt, or remove the override to use the "
                "system default."
            ),
        )
    if len(stripped) > USER_PROMPT_MAX_LENGTH:
        return ValidationResult(
            code=ValidationCode.TOO_LONG,
            message=(
                f"Your prompt is {len(stripped)} characters — the "
                f"maximum is {USER_PROMPT_MAX_LENGTH}."
            ),
        )
    lowered = stripped.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return ValidationResult(
                code=ValidationCode.BANNED_PHRASE,
                message=(
                    "Your prompt contains a phrase that would disable "
                    "Aurion's descriptive-mode safety boundary. Rephrase "
                    "without instructing the AI to interpret, diagnose, "
                    "recommend treatment, or override prior rules."
                ),
                matched_phrase=phrase,
            )
    # Anchor presence — at least one phrase from each conceptual group
    # must appear. Replacement semantics put the descriptive-mode
    # boundary entirely inside the physician's text; this is what
    # preserves CLAUDE.md's "describe, do not interpret" guarantee when
    # the base system prompt is no longer concatenated underneath.
    for group_idx, group in enumerate(DESCRIPTIVE_ANCHORS_REQUIRED):
        if not any(phrase in lowered for phrase in group):
            return ValidationResult(
                code=ValidationCode.MISSING_DESCRIPTIVE_ANCHOR,
                message=_anchor_failure_message(group_idx, group),
                missing_anchor_group=group_idx,
            )
    return ValidationResult(
        code=ValidationCode.OK,
        message="Prompt accepted.",
    )


# ── Specialty-guidance validation (ADDITIVE layer, not replacement) ─────────
#
# The per-specialty STYLE GUIDANCE block is layered ON TOP of the immutable
# base note-generation system prompt — it does NOT replace it (unlike the
# per-physician registry-prompt override above). The descriptive-mode
# boundary therefore still lives in the base system prompt, which is always
# present. So this validator runs the SAME injection / role-flip / "interpret
# the findings" banlist + a (shorter) length cap, but DOES NOT require the
# descriptive-mode anchor phrases: a legitimate style pointer like the
# shipped emergency-medicine guidance ("lead with vital signs … never infer
# severity or interpret results") is purely additive and would never pass the
# replacement-semantics anchor gate, yet is perfectly safe.

#: Specialty guidance is a focused style pointer, not a full standalone
#: system prompt — a tighter cap than ``USER_PROMPT_MAX_LENGTH`` keeps it
#: that way (a pointer that bloats into a second system prompt is a smell).
SPECIALTY_GUIDANCE_MAX_LENGTH: Final[int] = 2000


def validate_specialty_guidance(text: str) -> ValidationResult:
    """Structural safety check for physician-supplied specialty STYLE guidance.

    Same :class:`ValidationResult` shape as :func:`validate_user_prompt` so
    the API + UI reuse one error-handling path, but with two differences that
    follow from this text being ADDITIVE (layered on the always-present base
    system prompt) rather than a REPLACEMENT:

      1. Length cap is :data:`SPECIALTY_GUIDANCE_MAX_LENGTH` (tighter).
      2. The :data:`DESCRIPTIVE_ANCHORS_REQUIRED` gate is skipped — the base
         system prompt already carries the descriptive-mode boundary, so the
         guidance need not re-state it. The banlist still runs, so a physician
         cannot smuggle an interpretive / diagnostic / injection directive
         into the additive layer.

    Gate order: EMPTY → TOO_LONG → BANNED_PHRASE → OK.
    """
    stripped = text.strip() if text else ""
    if not stripped:
        return ValidationResult(
            code=ValidationCode.EMPTY,
            message=(
                "Your guidance is empty. Either add specialty style "
                "guidance, or remove the override to use the default."
            ),
        )
    if len(stripped) > SPECIALTY_GUIDANCE_MAX_LENGTH:
        return ValidationResult(
            code=ValidationCode.TOO_LONG,
            message=(
                f"Your guidance is {len(stripped)} characters — the "
                f"maximum is {SPECIALTY_GUIDANCE_MAX_LENGTH}."
            ),
        )
    lowered = stripped.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return ValidationResult(
                code=ValidationCode.BANNED_PHRASE,
                message=(
                    "Your guidance contains a phrase that would disable "
                    "Aurion's descriptive-mode safety boundary. Rephrase "
                    "without instructing the AI to interpret, diagnose, "
                    "recommend treatment, or override prior rules."
                ),
                matched_phrase=phrase,
            )
    return ValidationResult(
        code=ValidationCode.OK,
        message="Guidance accepted.",
    )


def _anchor_failure_message(group_idx: int, group: tuple[str, ...]) -> str:
    """Build a human-readable failure message naming the missing group.

    Lifted out of :func:`validate_user_prompt` so the message strings
    live next to the anchor-groups tuple they describe — easier to
    keep in sync when synonyms are added. The frontend ALSO has its
    own localised version of these messages indexed by
    ``missing_anchor_group``; this string is the EN fallback the API
    returns when the client doesn't render its own.
    """
    if group_idx == 0:
        examples = ", ".join(repr(p) for p in group[:3])
        return (
            "Your prompt must include language that says the AI should "
            "describe / document / record what was observed (examples: "
            f"{examples}). Without it, the descriptive-mode boundary "
            "cannot be enforced when your prompt replaces the system "
            "default."
        )
    if group_idx == 1:
        examples = ", ".join(repr(p) for p in group[:3])
        return (
            "Your prompt must include language that says the AI must "
            "NOT interpret / diagnose / infer (examples: "
            f"{examples}). Without it, the descriptive-mode boundary "
            "cannot be enforced when your prompt replaces the system "
            "default."
        )
    # Defensive fallback for future groups that haven't been wired into
    # the message helper yet — return a generic message rather than a
    # KeyError so adding a group doesn't crash the API.
    return (
        f"Your prompt is missing a required descriptive-mode anchor "
        f"(group {group_idx})."
    )
