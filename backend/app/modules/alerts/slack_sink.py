"""Slack delivery sink for CRITICAL operational alerts (#76).

Posts a compact, PHI-free message to a Slack incoming webhook whenever a
CRITICAL alert is published. Deliberately minimal:

- **Off until configured.** The webhook URL comes from the
  ``SLACK_ALERTS_WEBHOOK_URL`` env var (injected from Secrets Manager via
  the task definition, like the other secrets — never in code or
  Terraform state). Absent/empty → the sink is a no-op, logged once.
- **CRITICAL only.** Warning/info stay portal-only; Slack is the
  wake-someone-up channel. (#76's configurable thresholds can widen this
  later via AppConfig.)
- **Fire-and-forget.** Delivery runs as a detached task with a short
  timeout and swallows every failure — an unreachable Slack must never
  affect the clinical pipeline or the alert row itself (which is already
  committed; the portal remains the source of truth).
- **No PHI.** The payload carries alert_type / severity / source /
  message — publish-site messages are already PHI-free (session ids are
  truncated prefixes). The webhook URL is a secret and is never logged.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger("aurion.alerts.slack")

_TIMEOUT_SECONDS = 5.0
_ENV_VAR = "SLACK_ALERTS_WEBHOOK_URL"

# Log the "sink disabled" notice only once, not per alert.
_disabled_logged = False


def _webhook_url() -> str | None:
    url = os.getenv(_ENV_VAR, "").strip()
    return url or None


def is_configured() -> bool:
    return _webhook_url() is not None


async def notify_slack(
    *,
    alert_type: str,
    severity: str,
    source: str,
    message: str,
) -> bool:
    """POST one alert to the webhook. Returns delivery success; never
    raises. Safe to call unconfigured (returns False)."""
    url = _webhook_url()
    if url is None:
        return False
    payload = {
        "text": (
            f":rotating_light: *{severity.upper()}* — {message}\n"
            f"`{alert_type}` · {source} · Aurion dev"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 300:
            logger.warning(
                "Slack alert delivery failed: status=%s type=%s",
                resp.status_code,
                alert_type,
            )
            return False
        return True
    except Exception:  # noqa: BLE001 — delivery must never propagate
        logger.warning(
            "Slack alert delivery errored: type=%s", alert_type, exc_info=True
        )
        return False


def schedule_critical_notification(
    *,
    alert_type: str,
    severity: str,
    source: str,
    message: str,
) -> None:
    """Fire-and-forget Slack delivery for a CRITICAL alert.

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
                "Slack alert sink disabled (%s unset) — CRITICAL alerts are "
                "portal-only until the webhook secret is provisioned",
                _ENV_VAR,
            )
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (sync test context) — skip rather than crash.
        logger.warning("Slack sink: no running event loop; skipping delivery")
        return
    asyncio.create_task(
        notify_slack(
            alert_type=alert_type,
            severity=severity,
            source=source,
            message=message,
        )
    )
