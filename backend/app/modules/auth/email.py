"""Transactional email via AWS SES (AUTH-PIVOT-BACKEND).

Today the only template is the password-reset email. The helper is
intentionally narrow — when we add more templates (account-created,
MFA-cleared, etc.) they ship as additional functions in this module,
not as a generic "send anything" surface that callers would have to
keep PHI-free themselves.

LocalStack and dev workstations toggle SES off via ``AUTH_EMAIL_ENABLED=
false``. In that mode the reset link is logged at INFO so dev devs can
copy it out of the docker-compose log without standing up SES locally.

NEVER log the user's full email together with the reset link (the
combination is the credential). The dev-mode log line carries the email
and the link on the same line ONLY when AUTH_EMAIL_ENABLED is false —
that mode is local-only, not production.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.models import UserModel

logger = logging.getLogger("aurion.auth.email")

# ── Configuration ──────────────────────────────────────────────────────────
#
# AUTH_EMAIL_ENABLED defaults to false so a misconfigured dev env doesn't
# accidentally start blasting SES — opt-in for SES delivery, opt-out for
# log-only. AUTH_EMAIL_FROM is the verified sender identity in SES.
# AUTH_PASSWORD_RESET_URL_BASE is the URL the reset link points to;
# defaults to a localhost path so a forgotten env var produces a
# loud-but-harmless link.
_EMAIL_ENABLED = os.getenv("AUTH_EMAIL_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
_FROM_ADDRESS = os.getenv(
    "AUTH_EMAIL_FROM", "no-reply@aurionclinical.com"
)
_RESET_URL_BASE = os.getenv(
    "AUTH_PASSWORD_RESET_URL_BASE", "http://localhost:8000/reset-password"
)
_AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")

_ses_client: Any | None = None


def _get_ses_client() -> Any:
    """Cached boto3 SES client. Mirrors the s3 / kms pattern."""
    global _ses_client
    if _ses_client is None:
        kwargs: dict[str, Any] = {"region_name": _AWS_REGION}
        if _AWS_ENDPOINT_URL:
            kwargs["endpoint_url"] = _AWS_ENDPOINT_URL
        _ses_client = boto3.client("ses", **kwargs)
    return _ses_client


async def send_password_reset_email(
    *, user: UserModel, raw_token: str
) -> None:
    """Send a password-reset link to ``user``.

    The link is built from ``AUTH_PASSWORD_RESET_URL_BASE`` + the raw
    token as a ``?token=`` query string. In dev mode (when
    ``AUTH_EMAIL_ENABLED=false``) the link is logged to stdout
    instead of going through SES.

    The email contains the link, a 24-hour TTL hint, and the user's
    full name. NO session metadata. NO role. NO last-login info.
    Plain text + HTML are both sent so the user's MUA renders one.
    """
    reset_link = f"{_RESET_URL_BASE}?token={raw_token}"

    if not _EMAIL_ENABLED:
        # Dev-only path. The link contains the credential — log it once
        # at INFO so the dev workflow can complete without SES.
        logger.info(
            "AUTH_EMAIL_ENABLED=false — password reset link for %s: %s",
            user.email,
            reset_link,
        )
        return

    subject = "Reset your Aurion password"
    text_body = _build_text_body(user=user, reset_link=reset_link)
    html_body = _build_html_body(user=user, reset_link=reset_link)

    try:
        _get_ses_client().send_email(
            Source=_FROM_ADDRESS,
            Destination={"ToAddresses": [user.email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        # NEVER log the link in the success path — production audit only
        # carries user_id, never the credential.
        logger.info(
            "Password reset email sent (recipient redacted)"
        )
    except (BotoCoreError, ClientError) as e:
        # Production-mode failure. We log the SES exception class but
        # NOT the raw email body / link.
        logger.error("SES send_email failed: %s", type(e).__name__)
        raise


def _build_text_body(*, user: UserModel, reset_link: str) -> str:
    return (
        f"Hi {user.full_name or 'there'},\n\n"
        "You requested a password reset for your Aurion account. Open the\n"
        "link below within 24 hours to set a new password:\n\n"
        f"{reset_link}\n\n"
        "If you didn't request this, you can ignore this email — your\n"
        "password won't change.\n\n"
        "— The Aurion team\n"
    )


def _build_html_body(*, user: UserModel, reset_link: str) -> str:
    safe_name = (user.full_name or "there").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<html><body style='font-family: -apple-system, system-ui, sans-serif;'>"
        f"<p>Hi {safe_name},</p>"
        "<p>You requested a password reset for your Aurion account. "
        "Open the link below within 24 hours to set a new password:</p>"
        f"<p><a href='{reset_link}'>{reset_link}</a></p>"
        "<p>If you didn't request this, you can ignore this email — your "
        "password won't change.</p>"
        "<p>— The Aurion team</p>"
        "</body></html>"
    )


def _reset_client_for_tests() -> None:
    """Drop the cached SES client. Test helper — production never calls."""
    global _ses_client
    _ses_client = None


__all__ = ["send_password_reset_email"]
