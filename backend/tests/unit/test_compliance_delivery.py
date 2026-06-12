"""Unit tests for the #77 compliance-report email delivery.

Pins the safety gates: off-until-configured, PHI-free notice (metadata +
portal link only — never report bytes), failures swallowed, recipients
parsed from the env and never logged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.core.email_sender import EmailSendError
from app.modules.compliance import delivery

_WHEN = datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)
_ARGS = dict(
    report_type="masking",
    generated_at=_WHEN,
    sha256="a" * 64,
    byte_size=1536,
    since=datetime(2026, 6, 5, tzinfo=timezone.utc),
    until=_WHEN,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("COMPLIANCE_REPORT_RECIPIENTS", raising=False)
    monkeypatch.delenv("COMPLIANCE_REPORTS_URL", raising=False)
    delivery._disabled_logged = False
    yield


@pytest.mark.asyncio
async def test_unconfigured_is_noop_false() -> None:
    assert delivery.is_configured() is False
    assert await delivery.notify_report_generated(**_ARGS) is False


def test_recipients_parsed_and_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("COMPLIANCE_REPORT_RECIPIENTS", " co@x.com ,, audit@x.com ")
    assert delivery._recipients() == ["co@x.com", "audit@x.com"]
    assert delivery.is_configured() is True


@pytest.mark.asyncio
async def test_sends_metadata_only_no_report_bytes(monkeypatch) -> None:
    monkeypatch.setenv("COMPLIANCE_REPORT_RECIPIENTS", "co@aurionclinical.com")
    monkeypatch.setenv("COMPLIANCE_REPORTS_URL", "https://portal-dev.aurionclinical.com/portal/admin/compliance")
    with patch.object(delivery, "send_email", AsyncMock()) as mock_send:
        ok = await delivery.notify_report_generated(**_ARGS)
    assert ok is True
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to"] == ["co@aurionclinical.com"]
    assert "masking" in kwargs["subject"]
    body = kwargs["text_body"]
    assert "a" * 64 in body          # sha256 present
    assert "1536 bytes" in body      # size present
    assert "portal-dev.aurionclinical.com/portal/admin/compliance" in body  # link
    # The notice must NOT carry report content — only metadata. (No CSV
    # header rows / event fields leak in.)
    assert "session_id" not in body
    assert "event_timestamp" not in body


@pytest.mark.asyncio
async def test_link_omitted_when_portal_url_unset(monkeypatch) -> None:
    monkeypatch.setenv("COMPLIANCE_REPORT_RECIPIENTS", "co@aurionclinical.com")
    with patch.object(delivery, "send_email", AsyncMock()) as mock_send:
        await delivery.notify_report_generated(**_ARGS)
    assert "Download from the portal" not in mock_send.call_args.kwargs["text_body"]


@pytest.mark.asyncio
async def test_send_error_swallowed(monkeypatch) -> None:
    monkeypatch.setenv("COMPLIANCE_REPORT_RECIPIENTS", "co@aurionclinical.com")
    with patch.object(delivery, "send_email", AsyncMock(side_effect=EmailSendError("HTTP 500"))):
        assert await delivery.notify_report_generated(**_ARGS) is False


@pytest.mark.asyncio
async def test_unexpected_error_swallowed(monkeypatch) -> None:
    monkeypatch.setenv("COMPLIANCE_REPORT_RECIPIENTS", "co@aurionclinical.com")
    with patch.object(delivery, "send_email", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await delivery.notify_report_generated(**_ARGS) is False


def test_log_disabled_once_is_idempotent(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="aurion.compliance.delivery")
    delivery.log_disabled_once()
    delivery.log_disabled_once()
    disabled_lines = [r for r in caplog.records if "delivery disabled" in r.getMessage()]
    assert len(disabled_lines) == 1
