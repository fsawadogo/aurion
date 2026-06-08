"""Pilot metrics + provider configuration viewer.

Pilot metrics: paginated read of ``pilot_metrics`` rows with filters.
EVAL_TEAM or ADMIN.

Provider configuration: read-only AppConfig snapshot + config change
history (audit-derived). COMPLIANCE_OFFICER or ADMIN.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin._shared import (
    ConfigChangeEvent,
    MetricTimeseriesBucket,
    MetricTimeseriesResponse,
    PaginatedMetricsResponse,
    PilotMetricResponse,
    safe_json_parse,
    scan_audit_events,
)
from app.core.clock import utcnow
from app.core.database import get_db
from app.core.models import PilotMetricsModel
from app.core.types import UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_config

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/metrics", response_model=PaginatedMetricsResponse)
async def get_pilot_metrics(
    clinician_id: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Pilot metrics aggregate. EVAL_TEAM or ADMIN."""
    stmt = select(PilotMetricsModel).order_by(PilotMetricsModel.created_at.desc())

    if clinician_id:
        try:
            cid = uuid.UUID(clinician_id)
            stmt = stmt.where(PilotMetricsModel.clinician_id == cid)
        except ValueError:
            pass

    if specialty:
        stmt = stmt.where(PilotMetricsModel.specialty == specialty)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            stmt = stmt.where(PilotMetricsModel.created_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            stmt = stmt.where(PilotMetricsModel.created_at <= dt_to)
        except ValueError:
            pass

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Paginate
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = []
    for row in rows:
        # Parse physician_edit_rate from JSON
        edit_rate: Optional[float] = None
        if row.physician_edit_rate_json:
            try:
                rates = json.loads(row.physician_edit_rate_json)
                if isinstance(rates, dict) and rates:
                    edit_rate = sum(rates.values()) / len(rates)
                elif isinstance(rates, (int, float)):
                    edit_rate = float(rates)
            except (json.JSONDecodeError, TypeError):
                pass

        items.append(PilotMetricResponse(
            session_id=str(row.session_id),
            clinician_id=str(row.clinician_id),
            specialty=row.specialty,
            template_section_completeness=row.template_section_completeness,
            citation_traceability_rate=row.citation_traceability_rate,
            physician_edit_rate=edit_rate,
            conflict_rate=row.conflict_rate,
            low_confidence_frame_rate=row.low_confidence_frame_rate,
            stage1_latency_ms=row.stage1_latency_ms,
            stage2_latency_ms=row.stage2_latency_ms,
            session_completeness=row.session_completeness,
            # P1-FU-METRICS — additive; old clients ignore.
            clip_count=row.clip_count,
            clip_bytes_uploaded=row.clip_bytes_uploaded,
            clip_avg_latency_ms=row.clip_avg_latency_ms,
            clip_vision_spend_estimate_usd_micros=(
                row.clip_vision_spend_estimate_usd_micros
            ),
            clip_degraded_to_frame_count=row.clip_degraded_to_frame_count,
            created_at=row.created_at.isoformat() if row.created_at else "",
        ))

    return PaginatedMetricsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/metrics/timeseries", response_model=MetricTimeseriesResponse)
async def get_metrics_timeseries(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    clinician_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Per-day aggregates over the pilot_metrics window. EVAL_TEAM or ADMIN.

    Empty days are returned with session_count=0 + all metrics null so
    the frontend doesn't have to backfill gaps when drawing the chart.

    Default window is the last 14 days. `from`/`to` are ISO dates
    (YYYY-MM-DD); `to` is inclusive.
    """
    today = utcnow().date()
    try:
        end_date = datetime.fromisoformat(to).date() if to else today
    except ValueError:
        end_date = today
    try:
        start_date = (
            datetime.fromisoformat(from_).date()
            if from_
            else today - timedelta(days=13)
        )
    except ValueError:
        start_date = today - timedelta(days=13)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    day = func.date_trunc("day", PilotMetricsModel.created_at).label("day")

    stmt = (
        select(
            day,
            func.count().label("session_count"),
            func.avg(PilotMetricsModel.template_section_completeness).label(
                "template_section_completeness"
            ),
            func.avg(PilotMetricsModel.citation_traceability_rate).label(
                "citation_traceability_rate"
            ),
            # physician_edit_rate lives as JSON; the timeseries surfaces
            # only the numeric metrics directly. Edit-rate trends are a
            # follow-up (per-section breakdown is richer than one number).
            func.avg(PilotMetricsModel.conflict_rate).label("conflict_rate"),
            func.avg(PilotMetricsModel.low_confidence_frame_rate).label(
                "low_confidence_frame_rate"
            ),
            func.avg(PilotMetricsModel.stage1_latency_ms).label(
                "stage1_latency_ms"
            ),
            func.avg(PilotMetricsModel.stage2_latency_ms).label(
                "stage2_latency_ms"
            ),
            # session_completeness is Boolean → cast to Integer (1/0) first,
            # then average × 100 = % of that day's rows that were complete.
            # NB: Postgres cannot cast boolean directly to float
            # (asyncpg CannotCoerceError) — it must go bool→int. SQLite is
            # lax about this, which is why the unit test missed it.
            (
                func.avg(
                    func.cast(PilotMetricsModel.session_completeness, Integer)
                )
                * 100
            ).label("session_completeness"),
        )
        .where(
            PilotMetricsModel.created_at
            >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
            PilotMetricsModel.created_at
            < datetime.combine(
                end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            ),
        )
        .group_by(day)
        .order_by(day)
    )

    if specialty:
        stmt = stmt.where(PilotMetricsModel.specialty == specialty)
    if clinician_id:
        try:
            cid = uuid.UUID(clinician_id)
            stmt = stmt.where(PilotMetricsModel.clinician_id == cid)
        except ValueError:
            pass

    result = await db.execute(stmt)
    rows = result.all()

    # Index rows by ISO date for O(1) backfill lookup.
    by_date: dict[str, MetricTimeseriesBucket] = {}
    for r in rows:
        # r.day is a datetime at midnight UTC because DATE_TRUNC returns timestamptz.
        iso = r.day.date().isoformat() if hasattr(r.day, "date") else str(r.day)[:10]
        by_date[iso] = MetricTimeseriesBucket(
            date=iso,
            session_count=int(r.session_count or 0),
            template_section_completeness=(
                float(r.template_section_completeness)
                if r.template_section_completeness is not None
                else None
            ),
            citation_traceability_rate=(
                float(r.citation_traceability_rate)
                if r.citation_traceability_rate is not None
                else None
            ),
            physician_edit_rate=None,  # JSON shape — surfaced via /metrics list
            conflict_rate=(
                float(r.conflict_rate) if r.conflict_rate is not None else None
            ),
            low_confidence_frame_rate=(
                float(r.low_confidence_frame_rate)
                if r.low_confidence_frame_rate is not None
                else None
            ),
            stage1_latency_ms=(
                float(r.stage1_latency_ms)
                if r.stage1_latency_ms is not None
                else None
            ),
            stage2_latency_ms=(
                float(r.stage2_latency_ms)
                if r.stage2_latency_ms is not None
                else None
            ),
            session_completeness=(
                float(r.session_completeness)
                if r.session_completeness is not None
                else None
            ),
        )

    # Walk the date range so empty days come through as session_count=0.
    buckets: list[MetricTimeseriesBucket] = []
    cursor = start_date
    while cursor <= end_date:
        iso = cursor.isoformat()
        buckets.append(
            by_date.get(iso)
            or MetricTimeseriesBucket(date=iso, session_count=0)
        )
        cursor += timedelta(days=1)

    return MetricTimeseriesResponse(
        **{"from": start_date.isoformat(), "to": end_date.isoformat()},
        bucket="day",
        buckets=buckets,
    )


@router.get("/config/current")
async def get_current_config(
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """Current AppConfig state — read-only. COMPLIANCE_OFFICER or ADMIN."""
    config = get_config()
    return config.model_dump()


@router.get("/config/history", response_model=list[ConfigChangeEvent])
async def get_config_history(
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """Config change log from audit trail. COMPLIANCE_OFFICER or ADMIN."""
    audit = get_audit_log_service()
    all_events = await scan_audit_events(audit)

    config_events = [
        e for e in all_events if e.get("event_type") in ("config_changed", "provider_changed")
    ]

    result = []
    for evt in config_events:
        result.append(ConfigChangeEvent(
            id=evt.get("event_id", ""),
            changed_by=evt.get("changed_by", "system"),
            changed_at=evt.get("event_timestamp", ""),
            previous_config=safe_json_parse(evt.get("previous_config", "{}")),
            new_config=safe_json_parse(evt.get("new_config", "{}")),
            appconfig_version=int(evt.get("appconfig_version", 0)),
        ))

    return result
