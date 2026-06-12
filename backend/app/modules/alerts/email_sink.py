"""Email delivery sink for CRITICAL operational alerts (#76).

The email counterpart to ``slack_sink`` — emails a compact, PHI-free
notice whenever a CRITICAL alert is published. Same discipline:

- **Off until configured.** Recipients come from the
  ``ALERT_EMAIL_RECIPIENTS`` env var (comma-separated; wired via the task
  definition). Absent/empty → the sink is a no-op, logged once. The actual
  send goes through ``app.core.email_sender`` (Resend), so it also needs
  the email service configured (``RESEND_API_KEY`` + a verified sender).
- **CRITICAL only.** Warning/info stay portal-only — email is the
  wake-someone-up channel, same threshold as the Slack sink. (#76's
  configurable thresholds can widen this later via AppConfig.)
- **Fire-and-forget.** Delivery runs as a detached task and swallows every
  failure — an email outage must never affect the clinical pipeline or the
  alert row (already committed; the portal stays the source of truth).
- **No PHI.** The body carries alert_type / severity / source / message —
  publish-site messages are already PHI-free (session ids are truncated
  prefixes). Recipient addresses are never logged.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.core.email_sender import EmailSendError, send_email

logger = logging.getLogger("aurion.alerts.email")

_RECIPIENTS_ENV = "ALERT_EMAIL_RECIPIENTS"
# Reuse the verified transactional sender identity (a verified Resend
# domain). Same default as auth/email so a single AUTH_EMAIL_FROM governs.
_FROM_ADDRESS = os.getenv("AUTH_EMAIL_FROM", "no-reply@aurionclinical.com")

# Log the "sink disabled" notice only once, not per alert.
_disabled_logged = False


def _recipients() -> list[str]:
    raw = os.getenv(_RECIPIENTS_ENV, "")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def is_configured() -> bool:
    return len(_recipients()) > 0


async def notify_email(
    *,
    alert_type: str,
    severity: str,
    source: str,
    message: str,
) -> bool:
    """Email one alert to the configured recipients. Returns delivery
    success; never raises. Safe to call unconfigured (returns False)."""
    recipients = _recipients()
    if not recipients:
        return False

    subject = f"[Aurion {severity.upper()}] {alert_type}"
    text_body = (
        f"{severity.upper()} operational alert\n\n"
        f"{message}\n\n"
        f"type:   {alert_type}\n"
        f"source: {source}\n\n"
        "Open the Aurion portal → Alerts to acknowledge. "
        "This is an automated operational notice (no patient data)."
    )
    html_body = (
        "<html><body style='font-family:-apple-system,system-ui,sans-serif;'>"
        f"<p><strong>{severity.upper()} operational alert</strong></p>"
        f"<p>{_html_escape(message)}</p>"
        f"<p><code>{_html_escape(alert_type)}</code> · {_html_escape(source)}</p>"
        "<p>Open the Aurion portal → Alerts to acknowledge. "
        "Automated operational notice (no patient data).</p>"
        "</body></html>"
    )
    try:
        await send_email(
            to=recipients,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_address=_FROM_ADDRESS,
        )
        logger.info(
            "alert email delivered: type=%s severity=%s (recipients redacted)",
            alert_type,
            severity,
        )
        return True
    except EmailSendError:
        # The sender already logged a redacted provider+status. Delivery
        # must never propagate — the alert row is the source of truth.
        logger.warning("alert email delivery failed: type=%s", alert_type)
        return False
    except Exception:  # noqa: BLE001 — delivery must never propagate
        logger.warning(
            "alert email delivery errored: type=%s", alert_type, exc_info=True
        )
        return False


def schedule_critical_email_notification(
    *,
    alert_type: str,
    severity: str,
    source: str,
    message: str,
) -> None:
    """Fire-and-forget email delivery for a CRITICAL alert.

    Called from ``AlertService.publish`` after the row is flushed. Plain
    strings only — the detached task must not touch the request's DB
    session. No-op (with a one-time log) when unconfigured or when the
    severity isn't critical.
    """
    global _disabled_logged
    if severity != "critical":
        return
    if not is_configured():
        if not _disabled_logged:
            _disabled_logged = True
            logger.info(
                "Email alert sink disabled (%s unset) — CRITICAL alerts are "
                "portal-only until recipients are configured",
                _RECIPIENTS_ENV,
            )
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (sync test context) — skip rather than crash.
        logger.warning("Email sink: no running event loop; skipping delivery")
        return
    asyncio.create_task(
        notify_email(
            alert_type=alert_type,
            severity=severity,
            source=source,
            message=message,
        )
    )


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
