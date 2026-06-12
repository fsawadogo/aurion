"""Transactional email — password reset (AUTH-PIVOT-BACKEND).

Builds the password-reset message and hands it to the shared transport in
``app.core.email_sender`` (Resend by default; SES optional — see #399).
Today the only template is the password-reset email; new templates ship as
additional functions here, not as a generic "send anything" surface that
callers would have to keep PHI-free themselves.

LocalStack and dev workstations toggle delivery off via
``AUTH_EMAIL_ENABLED=false``. In that mode the reset link is logged at INFO
so dev devs can copy it out of the docker-compose log without standing up a
real email provider. That dev log-only path stays HERE (not in the shared
sender) because the reset link is a credential and the log line is
auth-specific.

NEVER log the user's full email together with the reset link (the
combination is the credential). The dev-mode log line carries the email and
the link on the same line ONLY when AUTH_EMAIL_ENABLED is false — that mode
is local-only, not production.
"""

from __future__ import annotations

import logging
import os

from app.core.email_sender import EmailSendError, send_email
from app.core.models import UserModel

logger = logging.getLogger("aurion.auth.email")

# ── Configuration ──────────────────────────────────────────────────────────
#
# AUTH_EMAIL_ENABLED defaults to false so a misconfigured dev env doesn't
# accidentally start sending real email — opt-in for delivery, opt-out for
# log-only. AUTH_EMAIL_FROM is the verified sender identity (a verified
# domain in Resend, or a verified SES identity). AUTH_PASSWORD_RESET_URL_BASE
# is the URL the reset link points to; defaults to a localhost path so a
# forgotten env var produces a loud-but-harmless link.
#
# Which provider actually sends (Resend vs SES) is owned by
# ``app.core.email_sender`` via EMAIL_PROVIDER — this module only decides
# enabled-vs-log-only and builds the message.
_EMAIL_ENABLED = os.getenv("AUTH_EMAIL_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
_FROM_ADDRESS = os.getenv("AUTH_EMAIL_FROM", "no-reply@aurionclinical.com")
_RESET_URL_BASE = os.getenv(
    "AUTH_PASSWORD_RESET_URL_BASE", "http://localhost:8000/reset-password"
)


async def send_password_reset_email(
    *, user: UserModel, raw_token: str
) -> None:
    """Send a password-reset link to ``user``.

    The link is built from ``AUTH_PASSWORD_RESET_URL_BASE`` + the raw token
    as a ``?token=`` query string. In dev mode (when
    ``AUTH_EMAIL_ENABLED=false``) the link is logged to stdout instead of
    being sent.

    The email contains the link, a 24-hour TTL hint, and the user's full
    name. NO session metadata. NO role. NO last-login info. Plain text +
    HTML are both sent so the user's MUA renders one.
    """
    reset_link = f"{_RESET_URL_BASE}?token={raw_token}"

    if not _EMAIL_ENABLED:
        # Dev-only path. The link contains the credential — log it once at
        # INFO so the dev workflow can complete without a real provider.
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
        await send_email(
            to=user.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_address=_FROM_ADDRESS,
        )
        # NEVER log the link/recipient in the success path — the shared
        # sender already logs a redacted line.
        logger.info("Password reset email dispatched")
    except EmailSendError:
        # Production-mode failure. The sender already logged the provider +
        # status (no PHI); re-raise so the caller (forgot-password) can
        # decide — it returns 204 regardless, never leaking the token.
        logger.error("Password reset email send failed")
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
    safe_name = (
        (user.full_name or "there").replace("<", "&lt;").replace(">", "&gt;")
    )
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


__all__ = ["send_password_reset_email"]
