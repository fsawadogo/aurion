"""Scheduled compliance-report generation (#77).

A lifespan worker that keeps a fresh signed snapshot of each report type
without an operator remembering to click Generate: on each pass, for
every ``ReportType``, if the newest persisted report is older than the
cadence, generate a new one covering the gap since that report (or the
full cadence window for the first ever).

Reports land in the same persisted + sha256-signed table the portal page
lists — **generation is scheduled; delivery is not** (emailing the file
lands as its own slice — now UNBLOCKED via Resend, see
app/core/email_sender.py; was gated on SES production access, #399).

## Configuration (env, mirroring the EMR worker / alert detectors)

  AURION_REPORT_SCHEDULER_ENABLED  — default ON ("1"); "0" disables.
    Low risk: one small signed CSV row per type per cadence.
  AURION_REPORT_CADENCE_HOURS      — default 168 (weekly), clamped [1, 720].
  AURION_REPORT_CHECK_INTERVAL_SECONDS — default 3600, clamped [300, 86400].

## Concurrency

Multiple replicas may pass simultaneously; the freshness check makes a
duplicate unlikely (both see the same newest row) and harmless (two
signed snapshots of the same window — extra row, no corruption). Pilot
runs a single task, so this stays theoretical.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Optional

from app.core.clock import utcnow
from app.core.database import async_session_factory
from app.modules.audit_log.service import get_audit_log_service
from app.modules.compliance.reports_service import (
    ReportType,
    get_compliance_reports_service,
)

logger = logging.getLogger("aurion.compliance.scheduler")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return min(max(int(os.getenv(name, default)), lo), hi)
    except ValueError:
        return default


def scheduler_enabled() -> bool:
    return os.getenv("AURION_REPORT_SCHEDULER_ENABLED", "1").lower() in (
        "1",
        "true",
        "yes",
    )


def cadence_hours() -> int:
    return _env_int("AURION_REPORT_CADENCE_HOURS", 168, 1, 720)


async def run_scheduler_pass(scan_events=None) -> int:
    """Generate any report type whose newest snapshot is stale. Returns
    the number generated. Never raises.

    ``scan_events`` injects the (expensive) audit scan for tests; in
    production it defaults to one full scan shared by every stale type in
    the pass (scan once, build many).
    """
    generated = 0
    try:
        service = get_compliance_reports_service()
        cadence = timedelta(hours=cadence_hours())
        now = utcnow()

        async with async_session_factory() as db:
            stale: list[tuple[ReportType, object]] = []
            for rtype in ReportType:
                newest = await service.list(db, report_type=rtype, limit=1)
                last_at = newest[0].generated_at if newest else None
                if last_at is None or (now - last_at) >= cadence:
                    stale.append((rtype, last_at))

            if not stale:
                return 0

            # One audit scan feeds every stale builder in this pass.
            if scan_events is None:
                from app.api.v1.admin._shared import scan_audit_events

                events = await scan_audit_events(get_audit_log_service())
            else:
                events = await scan_events()

            for rtype, last_at in stale:
                since = last_at if last_at is not None else now - cadence
                record = await service.generate(
                    db,
                    report_type=rtype,
                    events=events,
                    since=since,
                    until=now,
                    generated_by=None,  # system-generated; portal shows blank
                )
                generated += 1
                logger.info(
                    "scheduled %s report generated: id=%s bytes=%d",
                    rtype.value,
                    record.id,
                    record.byte_size,
                )
            await db.commit()
    except Exception:  # noqa: BLE001 — the loop must survive any pass error
        logger.exception("compliance report scheduler pass failed")
    return generated


_task: Optional[asyncio.Task] = None


async def _loop() -> None:
    interval = _env_int(
        "AURION_REPORT_CHECK_INTERVAL_SECONDS", 3600, 300, 86_400
    )
    while True:
        await asyncio.sleep(interval)
        await run_scheduler_pass()


async def start_report_scheduler() -> None:
    """Start the scheduler loop. Disabled when APP_ENV=local (mirrors the
    other lifespan pollers) or via the env kill-switch."""
    global _task
    if os.getenv("APP_ENV", "local") == "local":
        logger.info("report scheduler disabled (APP_ENV=local)")
        return
    if not scheduler_enabled():
        logger.info(
            "report scheduler disabled (AURION_REPORT_SCHEDULER_ENABLED=0)"
        )
        return
    _task = asyncio.create_task(_loop())
    logger.info(
        "compliance report scheduler started (cadence %dh)", cadence_hours()
    )


async def stop_report_scheduler() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    logger.info("compliance report scheduler stopped")
