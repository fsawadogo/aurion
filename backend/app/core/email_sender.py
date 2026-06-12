"""Provider-agnostic transactional email transport.

Aurion sends a handful of transactional emails — password reset today;
operational-alert delivery (#76) and compliance-report delivery (#77) once
those build on this. They used to go through AWS SES, but SES production
access was denied (#399), capping us at the sandbox (verified recipients
only). This module adds **Resend** as the sender — an HTTP email API with
no AWS-sandbox gate (verify a domain + use an API key, then send to anyone)
— selected via ``EMAIL_PROVIDER`` (default ``resend``). SES stays available
as an option for any environment that still has a working SES identity.

Callers build the message (subject + bodies) and hand it here; this module
owns only the transport. It lives in ``core/`` so auth, alerts, and
compliance can all share it without importing one another (CLAUDE.md
"modules never import each other — shared in core/").

PHI / secret discipline (CLAUDE.md §Privacy): this module NEVER logs the
recipient address, the message body, or the API key. Failures log the
provider name + HTTP status / exception class only.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aurion.email")

# Resend HTTP API. Base is overridable so tests can point at a mock and a
# future self-hosted relay is a config change, not a code change.
_RESEND_API_BASE = os.getenv("RESEND_API_BASE", "https://api.resend.com")
_RESEND_TIMEOUT_S = float(os.getenv("RESEND_TIMEOUT_SECONDS", "10"))

# SES (legacy / optional). Endpoint override mirrors the s3 / kms clients so
# LocalStack works in dev.
_AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")


class EmailSendError(RuntimeError):
    """Transport failed. The message carries provider + status only — never
    the recipient, body, or key (those must never reach logs/exceptions)."""


def _provider() -> str:
    """Selected email backend. Defaults to ``resend`` — SES production
    access was denied (#399), so Resend is the real sender; ``ses`` remains
    opt-in."""
    return os.getenv("EMAIL_PROVIDER", "resend").strip().lower()


async def send_email(
    *,
    to: list[str] | str,
    subject: str,
    text_body: str,
    html_body: str,
    from_address: str,
) -> None:
    """Send one transactional email via the configured provider.

    Raises ``EmailSendError`` on any failure (the caller decides whether to
    swallow it — e.g. forgot-password returns 204 regardless). Recipients
    and bodies are never logged.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        raise EmailSendError("send_email called with no recipients")

    provider = _provider()
    if provider == "resend":
        await _send_via_resend(
            recipients=recipients,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_address=from_address,
        )
    elif provider == "ses":
        await _send_via_ses(
            recipients=recipients,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_address=from_address,
        )
    else:
        # Misconfiguration — fail loud, leak nothing.
        raise EmailSendError(
            f"Unknown EMAIL_PROVIDER '{provider}' (expected 'resend' or 'ses')"
        )


# ── Resend ───────────────────────────────────────────────────────────────


async def _send_via_resend(
    *,
    recipients: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    from_address: str,
) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        # Misconfig (key not yet provisioned in Secrets Manager). Loud, but
        # leaks nothing — and forgot-password tolerates the raised error.
        raise EmailSendError("RESEND_API_KEY is not set")

    payload: dict[str, Any] = {
        "from": from_address,
        "to": recipients,
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    try:
        async with httpx.AsyncClient(timeout=_RESEND_TIMEOUT_S) as client:
            resp = await client.post(
                f"{_RESEND_API_BASE}/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.error("Resend request failed: %s", type(e).__name__)
        raise EmailSendError("Resend request failed") from e

    if resp.status_code >= 400:
        # Resend's error body can echo the recipient/subject — log the
        # status code only, never the response body.
        logger.error("Resend send failed: HTTP %s", resp.status_code)
        raise EmailSendError(f"Resend send failed: HTTP {resp.status_code}")

    logger.info("Email sent via Resend (recipient redacted)")


# ── SES (optional / legacy) ────────────────────────────────────────────────

_ses_client: Any | None = None


def _get_ses_client() -> Any:
    """Cached boto3 SES client. Mirrors the s3 / kms client pattern."""
    global _ses_client
    if _ses_client is None:
        import boto3

        kwargs: dict[str, Any] = {"region_name": _AWS_REGION}
        if _AWS_ENDPOINT_URL:
            kwargs["endpoint_url"] = _AWS_ENDPOINT_URL
        _ses_client = boto3.client("ses", **kwargs)
    return _ses_client


async def _send_via_ses(
    *,
    recipients: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    from_address: str,
) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    def _send() -> None:
        _get_ses_client().send_email(
            Source=from_address,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )

    try:
        # boto3 is synchronous — keep it off the event loop.
        await asyncio.to_thread(_send)
    except (BotoCoreError, ClientError) as e:
        logger.error("SES send_email failed: %s", type(e).__name__)
        raise EmailSendError("SES send failed") from e

    logger.info("Email sent via SES (recipient redacted)")


def _reset_clients_for_tests() -> None:
    """Drop cached clients. Test helper — production never calls."""
    global _ses_client
    _ses_client = None


__all__ = ["send_email", "EmailSendError"]
