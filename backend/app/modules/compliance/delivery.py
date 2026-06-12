"""Email delivery for scheduled compliance reports (#77).

The scheduler (``scheduler.py``) generates a signed CSV snapshot per type
on a cadence; this module emails a PHI-free *notice* to the configured
recipients so a compliance officer knows a fresh artifact is ready —
without an operator watching the portal.

Discipline (mirrors the #76 alert email sink):
- **Off until configured.** Recipients come from
  ``COMPLIANCE_REPORT_RECIPIENTS`` (comma-separated, task env). Empty →
  no-op. Delivery also needs the email service configured (Resend).
- **No PHI / no report bytes.** The email carries only metadata —
  report type, the time window, the sha256 signature, byte size, and a
  link to the portal Compliance page. The report CONTENT (which can hold
  audit/session data) stays behind the auth-gated portal download; we
  never attach it or inline it. Recipients are never logged.
- **Best-effort.** Never raises — a delivery failure must not break the
  scheduler pass (the report is already persisted; the portal is the
  source of truth).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from app.core.email_sender import EmailSendError, send_email

logger = logging.getLogger("aurion.compliance.delivery")

_RECIPIENTS_ENV = "COMPLIANCE_REPORT_RECIPIENTS"
_PORTAL_URL_ENV = "COMPLIANCE_REPORTS_URL"
_FROM_ADDRESS = os.getenv("AUTH_EMAIL_FROM", "no-reply@aurionclinical.com")

_disabled_logged = False


def _recipients() -> list[str]:
    raw = os.getenv(_RECIPIENTS_ENV, "")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def is_configured() -> bool:
    return len(_recipients()) > 0


def _portal_line() -> str:
    url = os.getenv(_PORTAL_URL_ENV, "").strip()
    return f"\nDownload from the portal: {url}\n" if url else ""


def _fmt(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else "—"


async def notify_report_generated(
    *,
    report_type: str,
    generated_at: datetime,
    sha256: str,
    byte_size: int,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    """Email a PHI-free 'report ready' notice. Returns delivery success;
    never raises. Safe to call unconfigured (returns False)."""
    recipients = _recipients()
    if not recipients:
        return False

    subject = f"[Aurion] {report_type} compliance report ready"
    portal = _portal_line()
    text_body = (
        f"A new {report_type} compliance report has been generated.\n\n"
        f"window:      {_fmt(since)} → {_fmt(until)}\n"
        f"generated:   {_fmt(generated_at)}\n"
        f"sha256:      {sha256}\n"
        f"size:        {byte_size} bytes\n"
        f"{portal}\n"
        "The report itself stays in the Aurion portal (auth-gated); this "
        "notice carries no patient data. Verify integrity against the "
        "sha256 above after download."
    )
    html_body = (
        "<html><body style='font-family:-apple-system,system-ui,sans-serif;'>"
        f"<p>A new <strong>{_esc(report_type)}</strong> compliance report has been generated.</p>"
        "<ul>"
        f"<li>window: {_esc(_fmt(since))} → {_esc(_fmt(until))}</li>"
        f"<li>generated: {_esc(_fmt(generated_at))}</li>"
        f"<li>sha256: <code>{_esc(sha256)}</code></li>"
        f"<li>size: {byte_size} bytes</li>"
        "</ul>"
        + (f"<p><a href='{_esc(os.getenv(_PORTAL_URL_ENV, '').strip())}'>Download from the portal</a></p>" if os.getenv(_PORTAL_URL_ENV, "").strip() else "")
        + "<p>The report stays in the Aurion portal (auth-gated); this notice "
        "carries no patient data. Verify integrity against the sha256 after "
        "download.</p>"
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
            "compliance report notice delivered: type=%s (recipients redacted)",
            report_type,
        )
        return True
    except EmailSendError:
        logger.warning("compliance report notice failed: type=%s", report_type)
        return False
    except Exception:  # noqa: BLE001 — delivery must never break the pass
        logger.warning(
            "compliance report notice errored: type=%s", report_type, exc_info=True
        )
        return False


def log_disabled_once() -> None:
    """One-time info log when the scheduler generates a report but no
    recipients are configured — so the dark state is visible without
    spamming every pass."""
    global _disabled_logged
    if not _disabled_logged:
        _disabled_logged = True
        logger.info(
            "compliance report email delivery disabled (%s unset) — reports "
            "are portal-only until recipients are configured",
            _RECIPIENTS_ENV,
        )


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
