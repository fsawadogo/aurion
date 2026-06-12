"""Unit coverage for the provider-agnostic email transport (Resend swap).

Covers provider selection, the Resend HTTP payload + auth header, the SES
fallback path, and the failure modes — asserting throughout that the
recipient, body, and API key never reach the logs (CLAUDE.md §Privacy).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import httpx
import pytest

from app.core import email_sender
from app.core.email_sender import EmailSendError, send_email

_MSG = {
    "to": "marie@aurionclinical.com",
    "subject": "Reset your Aurion password",
    "text_body": "open https://portal/reset?token=SECRETLINK",
    "html_body": "<p>open <a href='x'>link</a></p>",
    "from_address": "noreply@aurionclinical.com",
}


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def json(self) -> dict:
        return {"id": "re_123"}


def _fake_httpx(capture: dict, *, status: int = 200, raise_exc: Exception | None = None):
    """Build a drop-in replacement for httpx.AsyncClient that records the
    POST and returns a canned status (or raises)."""

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            capture["url"] = url
            capture["headers"] = headers
            capture["json"] = json
            if raise_exc is not None:
                raise raise_exc
            return _FakeResp(status)

    return _Client


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    email_sender._reset_clients_for_tests()
    yield
    email_sender._reset_clients_for_tests()


# ── Resend (default) ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resend_posts_expected_payload_and_auth(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _fake_httpx(cap))

    await send_email(**_MSG)

    assert cap["url"].endswith("/emails")
    assert cap["headers"]["Authorization"] == "Bearer re_test_key"
    body = cap["json"]
    assert body["from"] == "noreply@aurionclinical.com"
    assert body["to"] == ["marie@aurionclinical.com"]  # str normalized to list
    assert body["subject"] == _MSG["subject"]
    assert body["text"] == _MSG["text_body"]
    assert body["html"] == _MSG["html_body"]


@pytest.mark.asyncio
async def test_resend_accepts_list_recipients(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _fake_httpx(cap))
    await send_email(**{**_MSG, "to": ["a@x.com", "b@x.com"]})
    assert cap["json"]["to"] == ["a@x.com", "b@x.com"]


@pytest.mark.asyncio
async def test_resend_missing_key_raises_without_leaking(monkeypatch, caplog):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _fake_httpx({}))
    caplog.set_level(logging.DEBUG, logger="aurion.email")
    with pytest.raises(EmailSendError):
        await send_email(**_MSG)
    _assert_no_pii(caplog)


@pytest.mark.asyncio
async def test_resend_non_2xx_raises_status_only(monkeypatch, caplog):
    cap: dict = {}
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _fake_httpx(cap, status=422))
    caplog.set_level(logging.DEBUG, logger="aurion.email")
    with pytest.raises(EmailSendError) as ei:
        await send_email(**_MSG)
    assert "422" in str(ei.value)
    _assert_no_pii(caplog)


@pytest.mark.asyncio
async def test_resend_transport_error_raises(monkeypatch, caplog):
    monkeypatch.setattr(
        email_sender.httpx,
        "AsyncClient",
        _fake_httpx({}, raise_exc=httpx.ConnectError("boom")),
    )
    caplog.set_level(logging.DEBUG, logger="aurion.email")
    with pytest.raises(EmailSendError):
        await send_email(**_MSG)
    _assert_no_pii(caplog)


# ── SES (opt-in) ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ses_path_calls_boto_send_email(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    fake_ses = MagicMock()
    monkeypatch.setattr(email_sender, "_get_ses_client", lambda: fake_ses)

    await send_email(**_MSG)

    fake_ses.send_email.assert_called_once()
    kwargs = fake_ses.send_email.call_args.kwargs
    assert kwargs["Source"] == "noreply@aurionclinical.com"
    assert kwargs["Destination"] == {"ToAddresses": ["marie@aurionclinical.com"]}
    assert kwargs["Message"]["Subject"]["Data"] == _MSG["subject"]


# ── Selection + guards ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier_pigeon")
    with pytest.raises(EmailSendError):
        await send_email(**_MSG)


@pytest.mark.asyncio
async def test_empty_recipients_raises(monkeypatch):
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _fake_httpx({}))
    with pytest.raises(EmailSendError):
        await send_email(**{**_MSG, "to": []})


def _assert_no_pii(caplog) -> None:
    """No log line may carry the recipient, body, or API key."""
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "marie@aurionclinical.com" not in blob
    assert "re_test_key" not in blob
    assert "SECRETLINK" not in blob
