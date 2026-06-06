"""Shared cheap PHI/format gates for user-authored short text.

Used by:
  * `app/api/v1/sessions.py::_check_identifier_format` — patient identifier
    chip on `/sessions/{id}/external-reference-id`. (Issue #161.)
  * `app/api/v1/profile.py::_validate_consultation_type` — custom
    consultation type names on `PUT /profile`. (Issue #259.)

The intent is fail-closed against the most common foot-guns (a clinician
pastes a patient name, an email, an SSN into a short text field) without
trying to validate every imaginable scheme. Four explicit deny patterns
plus a length cap is the design.

The rejection ValueError NEVER carries the rejected value itself — the
value is itself potentially sensitive (could be a full patient name).
The reason string is short and reason-only. Pydantic catches the
ValueError and surfaces it as 422; `hide_input_in_errors=True` on the
caller's `model_config` is the second layer of defence that keeps the
rejected value out of the error's `input_value` field.
"""

from __future__ import annotations

import re

_SSN_RAW_RE = re.compile(r"^\d{9}$")
_SSN_DASHED_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$")


def validate_user_text(
    value: str,
    *,
    max_length: int,
    reject_full_name: bool = True,
) -> None:
    """Raise ``ValueError`` if ``value`` looks like obvious PHI.

    Caller is responsible for stripping whitespace before invoking — the
    empty / blank case is the caller's policy (e.g. patient identifier
    treats blank as a clear, consultation type treats blank as invalid).

    Parameters
    ----------
    value:
        The candidate string. Whitespace-stripped by the caller.
    max_length:
        Hard cap on the character length. Inclusive — i.e. a 64-char
        cap rejects 65-char inputs.
    reject_full_name:
        When True (default), a two-or-more-alpha-tokens shape (e.g.
        ``"Jane Doe"``) raises ``ValueError("text looks like a full name")``.
        Set False only if the field legitimately accepts multi-word
        human-friendly labels (none today; reserved for forward-compat).

    Raises
    ------
    ValueError
        With a short reason-only string. NEVER includes ``value``.
    """
    if len(value) > max_length:
        raise ValueError(f"text exceeds {max_length} character limit")
    if _SSN_RAW_RE.match(value) or _SSN_DASHED_RE.match(value):
        raise ValueError("text looks like an SSN")
    if "@" in value:
        raise ValueError("text looks like an email address")
    if reject_full_name:
        # Two-or-more whitespace-separated tokens with at least one
        # alphabetic character per token → looks like a full name. We
        # intentionally don't try to be clever about middle names /
        # hyphens / titles — if the legitimate value contains a space,
        # callers can paste it without spaces or use a delimiter their
        # downstream tooling expects.
        tokens = [t for t in value.split() if t]
        if len(tokens) >= 2 and all(
            any(c.isalpha() for c in t) for t in tokens
        ):
            raise ValueError("text looks like a full name")
