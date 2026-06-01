"""Unit tests for the physician macros service.

Locks the validation surface (shortcut format, body bounds, owner
scope) and the audit-event whitelist. The route layer is small enough
that the contract-level guarantees from `test_assert_owner.py` carry
over (owner scoping via service signature) without re-proving here.
"""

from __future__ import annotations

import pytest

from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
)
from app.modules.macros import service as macros

# ── Shortcut validation ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "shortcut",
    [
        "/ros",
        "/ros-cv",
        "/ros_cardiovascular",
        "/post-op-day-1",
        "/A",
        "/_",
        "/ros1",
    ],
)
def test_shortcut_valid(shortcut: str) -> None:
    """Common physician-grade shortcuts must validate."""
    assert macros._validate_shortcut(shortcut) == shortcut


@pytest.mark.parametrize(
    "shortcut",
    [
        "ros",                # missing leading slash
        "//ros",              # double slash
        "/ ros",              # space
        "/ros cv",            # space inside
        "/ros@cv",            # disallowed punctuation
        "/" + "a" * 33,       # too long
        "/",                  # just slash, no name
        "",                   # empty
        " ",                  # whitespace
    ],
)
def test_shortcut_invalid(shortcut: str) -> None:
    """Bad shapes must raise MacroError so the route returns 400."""
    with pytest.raises(macros.MacroError):
        macros._validate_shortcut(shortcut)


def test_shortcut_strips_surrounding_whitespace() -> None:
    """Trailing spaces from a clumsy paste shouldn't break validation."""
    assert macros._validate_shortcut("  /ros  ") == "/ros"


# ── Body validation ───────────────────────────────────────────────────────


def test_body_empty_refused() -> None:
    with pytest.raises(macros.MacroError, match="non-empty"):
        macros._validate_body("")


def test_body_whitespace_only_refused() -> None:
    with pytest.raises(macros.MacroError, match="non-empty"):
        macros._validate_body("   \n  ")


def test_body_over_limit_refused() -> None:
    with pytest.raises(macros.MacroError, match="4096"):
        macros._validate_body("x" * 4097)


def test_body_at_limit_accepted() -> None:
    assert macros._validate_body("x" * 4096) == "x" * 4096


def test_body_strips_outer_whitespace() -> None:
    assert macros._validate_body("\n  hello \n") == "hello"


# ── Audit event whitelist ────────────────────────────────────────────────


def test_macro_audit_events_do_not_carry_body() -> None:
    """The audit log is append-only — macro body is physician-personal
    phrasing and would be permanent if leaked there. Lock the kwargs
    whitelist."""
    for event in (
        AuditEventType.MACRO_CREATED,
        AuditEventType.MACRO_UPDATED,
        AuditEventType.MACRO_DELETED,
    ):
        allowed = ALLOWED_AUDIT_KWARGS.get(event)
        assert allowed is not None, f"No whitelist entry for {event}"
        assert "body" not in allowed
        assert "body_text" not in allowed


def test_macro_audit_enum_values_are_stable() -> None:
    """Existing DynamoDB rows reference these strings verbatim; lock
    them so a rename surfaces as a test failure, not silent drift."""
    assert AuditEventType.MACRO_CREATED.value == "macro_created"
    assert AuditEventType.MACRO_UPDATED.value == "macro_updated"
    assert AuditEventType.MACRO_DELETED.value == "macro_deleted"
