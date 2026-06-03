"""Structural safety validation for per-physician prompt overlays.

Phase B of AI Prompts Transparency. When a physician saves an overlay
on one of the catalog prompts (PATCH /me/prompts/{id}), this module is
the single gate the text passes through before the row is written.

The check is **structural only** by deliberate design:
  * length cap (1000 chars) so an overlay can't drown the base prompt
  * banlist of phrases that would compromise the descriptive-mode
    boundary the base prompt enforces

We deliberately do NOT call an LLM to judge intent. Reasons:
  1. Overkill before pilot data tells us what physicians actually try
     to write. An overlay editor with a 1k cap + a banlist is enough
     friction to catch the obvious jailbreaks (the only attack surface
     today since the same physician is also the safety reviewer).
  2. An LLM call would add cost + latency to every save. The save path
     is currently <50ms; an Anthropic round-trip would push it past
     2s.
  3. False positives from an LLM-based judge would be opaque to the
     physician. The banlist is transparent: the failure message echoes
     the exact phrase that tripped.

A future Phase C may layer a learned classifier on top, but the
banlist remains the floor.

DRY / SRP — single function, single banlist, single validation result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# ── Limits ──────────────────────────────────────────────────────────────────

#: Hard cap on overlay text length, in characters. Large enough for a
#: real preference paragraph (a typical example fits in <120 chars);
#: small enough that a malicious payload can't shadow the base prompt.
OVERLAY_MAX_LENGTH: Final[int] = 1000


# ── Banlist ─────────────────────────────────────────────────────────────────
#
# Phrases an overlay text MUST NOT contain. Match is case-insensitive
# substring — a longer/embedded match still trips. Each entry should be
# the shortest unambiguous form of the attack so the matcher catches
# common variants without an explosion of near-duplicates.
#
# Maintenance: add a new entry as a single tuple line with an inline
# comment explaining what attack it shuts down. Removing an entry
# requires explicit security review (and a corresponding test removal
# below — the unit tests assert one-rejection-per-entry so the banlist
# and tests stay in lock-step).
#
# CLAUDE.md grounding: every entry below targets a phrase that would
# weaken the descriptive-mode boundary the base prompts enforce
# ("Describe only what was directly captured"; "Do not infer,
# interpret, diagnose"). Letting any of these slip past would let the
# LLM cross the line from documentation into interpretation.

BANNED_PHRASES: Final[tuple[str, ...]] = (
    # Direct prompt-injection attempts targeting the base instructions.
    "ignore previous instructions",
    "ignore the above",
    "disregard prior rules",
    "system prompt override",
    "your new role is",
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
    # Generic instruction-replacement vector. Catching the verb +
    # "instruction" / "prompt" together is conservative; physicians
    # writing legitimate preferences never need to mention the words
    # in this combination.
    "override the system",
    "replace the system prompt",
)


# ── Result shape ────────────────────────────────────────────────────────────


class ValidationCode(StrEnum):
    """Outcome category for ``validate_overlay``.

    ``StrEnum`` so the API layer can serialize the code verbatim into
    the 400 response body — the frontend uses the code to pick the
    right localized error string and to highlight the matched phrase
    when applicable.
    """

    OK = "ok"
    TOO_LONG = "too_long"
    BANNED_PHRASE = "banned_phrase"
    EMPTY = "empty"


@dataclass(frozen=True)
class ValidationResult:
    """Structural validation outcome.

    ``message`` is safe to surface to the physician — no PHI, no
    secrets. ``matched_phrase`` is the exact banned phrase the input
    contained when ``code == BANNED_PHRASE``; safe to echo back so the
    physician knows which word tripped the gate. ``None`` otherwise.
    """

    code: ValidationCode
    message: str
    matched_phrase: str | None = None


# ── Public API ──────────────────────────────────────────────────────────────


def validate_overlay(text: str) -> ValidationResult:
    """Structural safety check for a physician-supplied overlay.

    Returns OK or a specific failure code. The matcher is intentionally
    simple — surrounding whitespace is stripped, then:

      1. Empty → ``EMPTY``
      2. Length > ``OVERLAY_MAX_LENGTH`` chars → ``TOO_LONG``
      3. Any ``BANNED_PHRASES`` entry appears (case-insensitive
         substring) → ``BANNED_PHRASE`` with ``matched_phrase`` set
      4. Otherwise → ``OK``

    The order matters: empty is detected before the length check so a
    blank input gives the physician the cleanest possible feedback.
    Length is checked before the banlist so a 10k-character paste
    doesn't pay the substring-scan cost. The banlist scan is short-
    circuit; the first matching phrase is the one reported (stable
    error UX — same input always produces the same matched phrase).
    """
    stripped = text.strip() if text else ""
    if not stripped:
        return ValidationResult(
            code=ValidationCode.EMPTY,
            message="Overlay text is empty. Add some preferences or reset to default.",
        )
    if len(stripped) > OVERLAY_MAX_LENGTH:
        return ValidationResult(
            code=ValidationCode.TOO_LONG,
            message=(
                f"Overlay text is {len(stripped)} characters — the maximum is "
                f"{OVERLAY_MAX_LENGTH}."
            ),
        )
    lowered = stripped.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return ValidationResult(
                code=ValidationCode.BANNED_PHRASE,
                message=(
                    "Overlay text contains a phrase that would weaken the "
                    "descriptive-mode safety boundary. Rephrase your preferences "
                    "without instructing the AI to interpret, diagnose, or "
                    "override prior rules."
                ),
                matched_phrase=phrase,
            )
    return ValidationResult(
        code=ValidationCode.OK,
        message="Overlay text accepted.",
    )
