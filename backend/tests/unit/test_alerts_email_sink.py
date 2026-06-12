"""Unit tests for the #76 email delivery sink.

Pins the same safety gates as the Slack sink: off-until-configured,
CRITICAL only, failures swallowed (never raises), recipients parsed from
the env, and the body carries only the already-PHI-free alert columns.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.email_sender import EmailSendError
from app.modules.alerts import email_sink


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_RECIPIENTS", raising=False)
    email_sink._disabled_logged = False
    yield


@pytest.mark.asyncio
async def test_unconfigured_is_noop_false() -> None:
    assert email_sink.is_configured() is False
    ok = await email_sink.notify_email(
        alert_type="purge_gap", severity="critical",
        source="purge_gap_detector", message="m",
    )
    assert ok is False


def test_recipients_parsed_and_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_EMAIL_RECIPIENTS", " a@x.com , ,b@x.com ")
    assert email_sink._recipients() == ["a@x.com", "b@x.com"]
    assert email_sink.is_configured() is True


@pytest.mark.asyncio
async def test_configured_sends_phi_free_body(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_EMAIL_RECIPIENTS", "ops@aurionclinical.com,co@aurionclinical.com")
    with patch.object(email_sink, "send_email", AsyncMock()) as mock_send:
        ok = await email_sink.notify_email(
            alert_type="purge_gap", severity="critical",
            source="purge_gap_detector",
            message="Session 1a2b3c4d transcribed 8h ago, no purge",
        )
    assert ok is True
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to"] == ["ops@aurionclinical.com", "co@aurionclinical.com"]
    assert "CRITICAL" in kwargs["subject"] and "purge_gap" in kwargs["subject"]
    for field in ("purge_gap", "purge_gap_detector", "Session 1a2b3c4d"):
        assert field in kwargs["text_body"]
    # The from-address is the verified transactional sender.
    assert "@" in kwargs["from_address"]


@pytest.mark.asyncio
async def test_send_error_swallowed(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_EMAIL_RECIPIENTS", "ops@aurionclinical.com")
    with patch.object(
        email_sink, "send_email", AsyncMock(side_effect=EmailSendError("HTTP 401"))
    ):
        ok = await email_sink.notify_email(
            alert_type="t", severity="critical", source="s", message="m",
        )
    assert ok is False  # never raises


@pytest.mark.asyncio
async def test_unexpected_error_swallowed(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_EMAIL_RECIPIENTS", "ops@aurionclinical.com")
    with patch.object(
        email_sink, "send_email", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        ok = await email_sink.notify_email(
            alert_type="t", severity="critical", source="s", message="m",
        )
    assert ok is False


@pytest.mark.asyncio
async def test_schedule_gates_on_severity(monkeypatch) -> None:
    import asyncio

    monkeypatch.setenv("ALERT_EMAIL_RECIPIENTS", "ops@aurionclinical.com")
    with patch.object(email_sink, "notify_email", AsyncMock()) as mock_notify:
        email_sink.schedule_critical_email_notification(
            alert_type="t", severity="warning", source="s", message="m",
        )
        await asyncio.sleep(0)
        mock_notify.assert_not_called()

        email_sink.schedule_critical_email_notification(
            alert_type="t", severity="critical", source="s", message="m",
        )
        await asyncio.sleep(0)
        mock_notify.assert_called_once()


def test_schedule_unconfigured_is_silent_noop() -> None:
    # No recipients, no running loop — must not raise.
    email_sink.schedule_critical_email_notification(
        alert_type="t", severity="critical", source="s", message="m",
    )
