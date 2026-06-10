"""Synthesized alert detectors (#76): SLA breaches + purge gaps.

The trigger-site publishes cover failures the code can see at the moment
they happen (Stage failures, provider errors). Two compliance-relevant
conditions are only visible by LOOKING — nothing fails when a note is
slow, and nothing fails when a purge never runs:

- **SLA breach** (warning): a session's ``stage1_latency_ms`` /
  ``stage2_latency_ms`` in ``pilot_metrics`` exceeded the MVP targets
  (Stage 1 < 30 s, Stage 2 < 5 min — CLAUDE.md success criteria).
- **Purge gap** (critical → Slack-eligible): a session has sat in
  ``EXPORTED`` longer than the allowed window without reaching
  ``PURGED``. "Raw data purge confirmed every session" is an MVP
  criterion and a Law-25 posture commitment; a gap is the kind of thing
  the compliance officer must hear about before an auditor does.

A background worker (started from the FastAPI lifespan, mirroring the
EMR retry worker) runs both detector passes on a cadence. Each pass is a
pure-ish function over its own short-lived DB session so it is unit
testable; alerts are deduplicated against existing rows by
``(alert_type, metadata.session_id)`` within a lookback window, so a
restart or a second replica never spams duplicates.

## Configuration (env, mirroring the EMR worker's knobs)

  AURION_ALERT_DETECTORS_ENABLED   — default ON ("1"); set "0" to disable.
    Unlike the EMR worker (which mutates an external system and is
    opt-in), detectors only read state and insert alert rows.
  AURION_ALERT_DETECT_INTERVAL_SECONDS — default 300, clamped [60, 3600].
  Thresholds come from AppConfig (``alerting`` block: sla_stage1_ms /
  sla_stage2_ms / purge_gap_hours — #76 "configurable thresholds"); the
  env vars below OVERRIDE AppConfig when set (ops escape hatch):
  AURION_SLA_STAGE1_MS             — AppConfig default 30000  (Stage 1 < 30 s)
  AURION_SLA_STAGE2_MS             — AppConfig default 300000 (Stage 2 < 5 min)
  AURION_PURGE_GAP_HOURS           — AppConfig default 24
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.database import async_session_factory
from app.core.models import AlertModel, PilotMetricsModel, SessionModel
from app.core.types import SessionState
from app.modules.alerts.service import AlertSeverity, get_alert_service

logger = logging.getLogger("aurion.alerts.detectors")

# Alert types synthesized here (freeform per AlertModel's contract).
SLA_BREACH_STAGE1 = "sla_breach_stage1"
SLA_BREACH_STAGE2 = "sla_breach_stage2"
PURGE_GAP = "purge_gap"

# How far back the dedup existence-check looks. Anything older than this
# that is STILL broken will re-alert — deliberate: a week-old unpurged
# session should resurface, not stay silenced forever.
_DEDUP_LOOKBACK = timedelta(days=7)

# How far back each scan pass looks for offending rows. Bounded so the
# pass stays cheap; the dedup set keeps repeats quiet within the window.
_SCAN_LOOKBACK = timedelta(days=2)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return min(max(int(os.getenv(name, default)), lo), hi)
    except ValueError:
        return default


def detectors_enabled() -> bool:
    return os.getenv("AURION_ALERT_DETECTORS_ENABLED", "1").lower() in (
        "1",
        "true",
        "yes",
    )


def _threshold(env_name: str, appconfig_value: int, lo: int, hi: int) -> int:
    """Resolve a detector threshold: env override > AppConfig > schema
    default (the AppConfig value already carries the schema default when
    the hosted content omits the ``alerting`` block). The env var is the
    ops escape hatch and is clamped to the same bounds as the schema."""
    if os.getenv(env_name) is not None:
        return _env_int(env_name, appconfig_value, lo, hi)
    return min(max(appconfig_value, lo), hi)


def _alerting_config():
    """Late import so unit tests can run detectors without the AppConfig
    client started; falls back to schema defaults on any client error."""
    try:
        from app.modules.config.appconfig_client import get_config

        return get_config().alerting
    except Exception:  # noqa: BLE001 — detector pass must survive config hiccups
        from app.modules.config.schema import AlertingConfig

        return AlertingConfig()


def sla_stage1_ms() -> int:
    return _threshold(
        "AURION_SLA_STAGE1_MS", _alerting_config().sla_stage1_ms, 1_000, 3_600_000
    )


def sla_stage2_ms() -> int:
    return _threshold(
        "AURION_SLA_STAGE2_MS", _alerting_config().sla_stage2_ms, 1_000, 86_400_000
    )


def purge_gap_hours() -> int:
    return _threshold(
        "AURION_PURGE_GAP_HOURS", _alerting_config().purge_gap_hours, 1, 24 * 14
    )


async def _already_alerted(
    db: AsyncSession, alert_type: str
) -> set[str]:
    """Session ids already carrying an alert of ``alert_type`` within the
    dedup lookback — read once per pass, not per candidate."""
    result = await db.execute(
        select(AlertModel.alert_metadata).where(
            AlertModel.alert_type == alert_type,
            AlertModel.created_at >= utcnow() - _DEDUP_LOOKBACK,
        )
    )
    out: set[str] = set()
    for (meta,) in result.all():
        if isinstance(meta, dict) and meta.get("session_id"):
            out.add(str(meta["session_id"]))
    return out


def _session_prefix(session_id) -> str:
    """8-char prefix — alert messages stay greppable without carrying the
    full (PHI-adjacent) UUID; the full id rides in metadata for the
    portal, same as the existing trigger-site publishes."""
    return str(session_id)[:8]


async def run_sla_pass(db: AsyncSession) -> int:
    """Scan recent pilot_metrics for stage latencies over the SLA targets;
    publish one warning per (session, stage). Returns alerts published."""
    s1_limit, s2_limit = sla_stage1_ms(), sla_stage2_ms()
    result = await db.execute(
        select(
            PilotMetricsModel.session_id,
            PilotMetricsModel.stage1_latency_ms,
            PilotMetricsModel.stage2_latency_ms,
        ).where(PilotMetricsModel.created_at >= utcnow() - _SCAN_LOOKBACK)
    )
    rows = result.all()

    service = get_alert_service()
    published = 0
    seen_s1 = await _already_alerted(db, SLA_BREACH_STAGE1)
    seen_s2 = await _already_alerted(db, SLA_BREACH_STAGE2)

    for row in rows:
        sid = str(row.session_id)
        if row.stage1_latency_ms is not None and row.stage1_latency_ms > s1_limit:
            if sid not in seen_s1:
                await service.publish(
                    db,
                    alert_type=SLA_BREACH_STAGE1,
                    severity=AlertSeverity.WARNING,
                    source="alert_detectors",
                    message=(
                        f"Stage 1 took {row.stage1_latency_ms / 1000:.1f}s "
                        f"(SLA {s1_limit / 1000:.0f}s) for session "
                        f"{_session_prefix(sid)}"
                    ),
                    metadata={
                        "session_id": sid,
                        "latency_ms": row.stage1_latency_ms,
                        "sla_ms": s1_limit,
                    },
                )
                seen_s1.add(sid)
                published += 1
        if row.stage2_latency_ms is not None and row.stage2_latency_ms > s2_limit:
            if sid not in seen_s2:
                await service.publish(
                    db,
                    alert_type=SLA_BREACH_STAGE2,
                    severity=AlertSeverity.WARNING,
                    source="alert_detectors",
                    message=(
                        f"Stage 2 took {row.stage2_latency_ms / 1000:.0f}s "
                        f"(SLA {s2_limit / 1000:.0f}s) for session "
                        f"{_session_prefix(sid)}"
                    ),
                    metadata={
                        "session_id": sid,
                        "latency_ms": row.stage2_latency_ms,
                        "sla_ms": s2_limit,
                    },
                )
                seen_s2.add(sid)
                published += 1
    return published


async def run_purge_gap_pass(db: AsyncSession) -> int:
    """Sessions stuck in EXPORTED past the purge window → one CRITICAL
    alert each (Slack-eligible via the #406 sink). Returns count."""
    gap = timedelta(hours=purge_gap_hours())
    cutoff = utcnow() - gap
    result = await db.execute(
        select(SessionModel.id, SessionModel.updated_at).where(
            SessionModel.state == SessionState.EXPORTED,
            SessionModel.updated_at < cutoff,
        )
    )
    rows = result.all()

    service = get_alert_service()
    seen = await _already_alerted(db, PURGE_GAP)
    published = 0
    for row in rows:
        sid = str(row.id)
        if sid in seen:
            continue
        hours_stuck = (utcnow() - row.updated_at).total_seconds() / 3600
        await service.publish(
            db,
            alert_type=PURGE_GAP,
            severity=AlertSeverity.CRITICAL,
            source="alert_detectors",
            message=(
                f"Session {_session_prefix(sid)} exported "
                f"{hours_stuck:.0f}h ago and is still not purged "
                f"(window {purge_gap_hours()}h)"
            ),
            metadata={
                "session_id": sid,
                "hours_since_export": round(hours_stuck, 1),
                "window_hours": purge_gap_hours(),
            },
        )
        seen.add(sid)
        published += 1
    return published


async def run_detector_pass() -> int:
    """One full pass over both detectors in its own session. Never raises."""
    try:
        async with async_session_factory() as db:
            n = await run_sla_pass(db)
            n += await run_purge_gap_pass(db)
            await db.commit()
        if n:
            logger.info("alert detectors: published %d alert(s)", n)
        return n
    except Exception:  # noqa: BLE001 — the loop must survive any pass error
        logger.exception("alert detector pass failed")
        return 0


_task: Optional[asyncio.Task] = None


async def _loop() -> None:
    interval = _env_int("AURION_ALERT_DETECT_INTERVAL_SECONDS", 300, 60, 3600)
    while True:
        await asyncio.sleep(interval)
        await run_detector_pass()


async def start_alert_detectors() -> None:
    """Start the detector loop. Disabled when APP_ENV=local (no DB poller
    in unit tests / local dev, mirroring the override pollers) or when
    the env kill-switch is off."""
    global _task
    if os.getenv("APP_ENV", "local") == "local":
        logger.info("alert detectors disabled (APP_ENV=local)")
        return
    if not detectors_enabled():
        logger.info("alert detectors disabled (AURION_ALERT_DETECTORS_ENABLED=0)")
        return
    _task = asyncio.create_task(_loop())
    logger.info(
        "alert detectors started (SLA s1>%dms s2>%dms, purge gap %dh)",
        sla_stage1_ms(),
        sla_stage2_ms(),
        purge_gap_hours(),
    )


async def stop_alert_detectors() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    logger.info("alert detectors stopped")
