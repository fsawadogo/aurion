"""Format gates on PATCH /sessions/{id}/identifier (issue #161, AC-4).

Locks the four deny patterns + length cap defined in
`app.api.v1.sessions._check_identifier_format`:

  1. raw 9-digit SSN (`123456789`) → 422
  2. dashed SSN (`123-45-6789`) → 422
  3. anything containing `@` (email) → 422
  4. two-or-more whitespace-separated alphabetic tokens (full name) → 422
  5. anything longer than 64 chars → 422

And confirms the accept path still round-trips the canonical clinic
identifier shapes (MRN-style, free hyphen-id, single-token alphanumeric)
unchanged through the existing encrypt + audit pipeline.

Stays in the unit tier — Pydantic validation only, no DB, no KMS. The
existing `test_session_identifier.py` already covers the encrypt /
decrypt / audit story; this module is the front-door gate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.sessions import (
    ExternalReferenceIdRequest,
    _check_identifier_format,
)

# ── Deny patterns ──────────────────────────────────────────────────────────


def test_rejects_raw_ssn():
    """123456789 — most common foot-gun: pasted SSN with no formatting."""
    with pytest.raises(ValidationError) as exc:
        ExternalReferenceIdRequest(external_reference_id="123456789")
    # Reason string should describe shape, NOT echo the value back.
    assert "SSN" in str(exc.value)
    assert "123456789" not in str(exc.value)


def test_rejects_dashed_ssn():
    """123-45-6789 — common pasted format from US patient charts."""
    with pytest.raises(ValidationError) as exc:
        ExternalReferenceIdRequest(external_reference_id="123-45-6789")
    assert "SSN" in str(exc.value)
    assert "123-45-6789" not in str(exc.value)


def test_rejects_email():
    """A literal `@` anywhere in the value flags as email-shaped."""
    with pytest.raises(ValidationError) as exc:
        ExternalReferenceIdRequest(external_reference_id="patient@example.com")
    assert "email" in str(exc.value).lower()
    assert "patient@example.com" not in str(exc.value)


def test_rejects_email_with_subdomain():
    with pytest.raises(ValidationError):
        ExternalReferenceIdRequest(
            external_reference_id="jane.doe+followup@clinic.lan"
        )


def test_rejects_full_name_two_tokens():
    """`Jane Doe` — two whitespace-separated alphabetic tokens."""
    with pytest.raises(ValidationError) as exc:
        ExternalReferenceIdRequest(external_reference_id="Jane Doe")
    assert "name" in str(exc.value).lower()
    assert "Jane Doe" not in str(exc.value)


def test_rejects_full_name_three_tokens():
    """`Jane M Doe` — middle initial doesn't bypass the gate."""
    with pytest.raises(ValidationError):
        ExternalReferenceIdRequest(external_reference_id="Jane M Doe")


def test_rejects_overlong():
    """65+ chars → 422. Cap is 64 (matches `_MAX_IDENTIFIER_LEN`)."""
    with pytest.raises(ValidationError) as exc:
        ExternalReferenceIdRequest(external_reference_id="A" * 65)
    assert "64" in str(exc.value) or "character" in str(exc.value).lower()
    # NEVER echo the rejected value (could be the start of a name).
    assert "A" * 65 not in str(exc.value)


def test_rejects_at_exact_overlong_boundary():
    """Boundary: 65 chars fails. 64 chars should still pass."""
    with pytest.raises(ValidationError):
        ExternalReferenceIdRequest(external_reference_id="X" * 65)
    # And 64 is the upper bound that's still accepted:
    ok = ExternalReferenceIdRequest(external_reference_id="Y" * 64)
    assert ok.external_reference_id == "Y" * 64


# ── Accept patterns (regression for canonical clinic schemes) ──────────────


@pytest.mark.parametrize(
    "value",
    [
        "MRN-12345",        # hyphen-separated, all-uppercase token
        "MRN_12345",        # underscore
        "12345",            # numeric-only short
        "AB123456",         # mixed-case-alphanumeric
        "2026-06-01-AB",    # date-prefixed encounter id
        "0001-CCQ-FRENCH",  # CREOQ / Québec scheme
        "patient42",        # single token
        "X" * 64,           # exactly at the cap
        "FOLLOWUP_2026Q2",
    ],
)
def test_accepts_canonical_identifier_shapes(value: str):
    """The accept path round-trips the value untouched (encryption,
    hashing, audit all run as before — verified by the existing
    test_session_identifier.py suite)."""
    body = ExternalReferenceIdRequest(external_reference_id=value)
    assert body.external_reference_id == value


def test_accepts_null():
    """null clears the column. No format check applies."""
    body = ExternalReferenceIdRequest(external_reference_id=None)
    assert body.external_reference_id is None


def test_accepts_empty_string():
    """Empty string → cleared. Format check skipped because the route
    handler interprets blank-after-strip as a clear."""
    body = ExternalReferenceIdRequest(external_reference_id="")
    assert body.external_reference_id == ""


def test_accepts_whitespace_only():
    """All-whitespace → treated as clear (route handler strips). The
    validator must not 422 on whitespace alone — that would force
    the portal to call DELETE for clear, breaking the existing
    contract."""
    body = ExternalReferenceIdRequest(external_reference_id="   ")
    assert body.external_reference_id == "   "


# ── Internal helper invariants ─────────────────────────────────────────────


def test_helper_rejects_value_but_never_echoes_it():
    """Direct test of the helper so it stays useful if Pydantic
    wrapping changes. Importantly: the raised ValueError message
    MUST NOT contain the rejected value — PHI never lands in logs
    via exception bubbling."""
    for bad in (
        "123456789",
        "patient@example.com",
        "Jane Q Smith",
        "Z" * 100,
    ):
        with pytest.raises(ValueError) as exc:
            _check_identifier_format(bad)
        assert bad not in str(exc.value), (
            "Rejection reason must not echo the rejected identifier"
        )


def test_helper_accepts_canonical():
    """Canonical clinic identifier should not raise."""
    # No exception → pass.
    _check_identifier_format("MRN-12345")
    _check_identifier_format("2026-06-01-AB")
    _check_identifier_format("patient42")
