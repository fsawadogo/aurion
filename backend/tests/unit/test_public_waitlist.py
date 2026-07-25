"""Unit tests — public waitlist endpoint (peritwin.com contact form)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.api.v1.public_waitlist import (
    WaitlistSignupRequest,
    create_waitlist_signup,
)
from app.core.models import WaitlistSignupModel


def _valid_payload(**overrides: object) -> dict:
    base: dict = {
        "name": "Dr. Test Surgeon",
        "email": "Surgeon@Example.COM",
        "reason": "pilot",
        "specialty": "Orthopedic surgery",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema — the only unauthenticated write surface, so the allow-list matters
# ---------------------------------------------------------------------------


def test_schema_accepts_valid_payload() -> None:
    req = WaitlistSignupRequest(**_valid_payload())
    assert req.reason == "pilot"


def test_schema_specialty_is_optional() -> None:
    payload = _valid_payload()
    del payload["specialty"]
    req = WaitlistSignupRequest(**payload)
    assert req.specialty is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"reason": "sales"},  # not in the enum
        {"name": ""},
        {"name": "x" * 201},
        {"specialty": "x" * 201},
    ],
)
def test_schema_rejects_bad_fields(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        WaitlistSignupRequest(**_valid_payload(**overrides))


def test_schema_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WaitlistSignupRequest(**_valid_payload(admin=True))


# ---------------------------------------------------------------------------
# Handler — inserts a normalized row and commits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_signup_inserts_normalized_row() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    body = WaitlistSignupRequest(
        **_valid_payload(name="  Dr. Test Surgeon  ", specialty="  Ortho  ")
    )
    resp = await create_waitlist_signup(body, db)

    assert resp.ok is True
    assert db.add.called
    row = db.add.call_args[0][0]
    assert isinstance(row, WaitlistSignupModel)
    assert row.name == "Dr. Test Surgeon"  # trimmed
    assert row.email == "surgeon@example.com"  # lowercased
    assert row.reason == "pilot"
    assert row.specialty == "Ortho"
    assert row.source == "website"
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_create_signup_without_specialty() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    payload = _valid_payload(reason="general")
    del payload["specialty"]
    resp = await create_waitlist_signup(WaitlistSignupRequest(**payload), db)

    assert resp.ok is True
    assert db.add.call_args[0][0].specialty is None


# ---------------------------------------------------------------------------
# Notification email — best-effort, never breaks the form
# ---------------------------------------------------------------------------


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_notification_sent_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("WAITLIST_NOTIFY_EMAIL", "team@example.com")
    sent = AsyncMock()
    monkeypatch.setattr("app.api.v1.public_waitlist.send_email", sent)

    resp = await create_waitlist_signup(
        WaitlistSignupRequest(**_valid_payload()), _mock_db()
    )

    assert resp.ok is True
    assert sent.await_count == 1
    kwargs = sent.await_args.kwargs
    assert kwargs["to"] == "team@example.com"
    assert "pilot" in kwargs["subject"]
    assert "surgeon@example.com" in kwargs["text_body"]


@pytest.mark.asyncio
async def test_notification_skipped_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("WAITLIST_NOTIFY_EMAIL", raising=False)
    sent = AsyncMock()
    monkeypatch.setattr("app.api.v1.public_waitlist.send_email", sent)

    resp = await create_waitlist_signup(
        WaitlistSignupRequest(**_valid_payload()), _mock_db()
    )

    assert resp.ok is True
    assert sent.await_count == 0


@pytest.mark.asyncio
async def test_send_failure_does_not_break_form(monkeypatch) -> None:
    from app.core.email_sender import EmailSendError

    monkeypatch.setenv("WAITLIST_NOTIFY_EMAIL", "team@example.com")
    sent = AsyncMock(side_effect=EmailSendError("resend 500"))
    monkeypatch.setattr("app.api.v1.public_waitlist.send_email", sent)

    resp = await create_waitlist_signup(
        WaitlistSignupRequest(**_valid_payload()), _mock_db()
    )

    assert resp.ok is True  # the signup is stored; email failure is swallowed
    assert sent.await_count == 1


@pytest.mark.asyncio
async def test_notification_escapes_html_in_lead_fields(monkeypatch) -> None:
    monkeypatch.setenv("WAITLIST_NOTIFY_EMAIL", "team@example.com")
    sent = AsyncMock()
    monkeypatch.setattr("app.api.v1.public_waitlist.send_email", sent)

    await create_waitlist_signup(
        WaitlistSignupRequest(
            **_valid_payload(name="<img src=x onerror=alert(1)>")
        ),
        _mock_db(),
    )

    html_body = sent.await_args.kwargs["html_body"]
    assert "<img" not in html_body
    assert "&lt;img" in html_body
