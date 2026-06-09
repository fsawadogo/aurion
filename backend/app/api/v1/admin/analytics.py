"""Adoption & ROI analytics rollup (issue #71, slice 1).

One aggregation endpoint the portal analytics page (slice 2) reads:
per-clinician + aggregate adoption (active clinicians, sessions, exported
notes, notes per active day) joined with the pilot-metrics quality averages
(completeness, citation traceability, edit rate, latencies).

Time-saved is deliberately NOT computed from a hardcoded baseline: the
caller passes ``baseline_minutes_per_note`` explicitly and the response
echoes it back, so every time-saved figure is traceable to the assumption
that produced it (descriptive-mode discipline applied to analytics — we
report measured counts; the estimate is opt-in and labeled). Without the
parameter, ``time_saved_minutes`` is null.

EVAL_TEAM or ADMIN — same gate as the pilot-metrics reads. No PHI: counts,
rates, latencies, and clinician (user) emails only.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import PilotMetricsModel, SessionModel, UserModel
from app.core.types import SessionState, UserRole
from app.modules.auth.service import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])

# States that count as a delivered note for adoption math. EXPORTED is the
# clinician-visible outcome; PURGED sessions were exported first (purge is
# the post-export cleanup), so they still count.
_EXPORTED_STATES = (SessionState.EXPORTED, SessionState.PURGED)


# ── Response models ──────────────────────────────────────────────────────────


class ClinicianAdoptionRow(BaseModel):
    clinician_id: str
    email: str | None
    sessions_total: int
    sessions_exported: int
    active_days: int
    notes_per_active_day: float
    avg_completeness: float | None
    avg_citation_traceability: float | None
    avg_edit_rate: float | None
    avg_stage1_latency_ms: float | None
    avg_stage2_latency_ms: float | None
    time_saved_minutes: float | None
    last_active_at: str | None


class AdoptionTotals(BaseModel):
    active_clinicians: int
    sessions_total: int
    sessions_exported: int
    notes_per_active_day: float
    avg_completeness: float | None
    avg_citation_traceability: float | None
    avg_edit_rate: float | None
    avg_stage1_latency_ms: float | None
    avg_stage2_latency_ms: float | None
    time_saved_minutes: float | None


class AdoptionResponse(BaseModel):
    since: datetime | None
    until: datetime | None
    baseline_minutes_per_note: float | None
    totals: AdoptionTotals
    by_clinician: list[ClinicianAdoptionRow]


# ── Pure aggregation (unit-testable without a DB) ────────────────────────────


@dataclass
class SessionAgg:
    """Per-clinician session aggregate as plain data."""

    clinician_id: uuid.UUID
    sessions_total: int
    sessions_exported: int
    active_days: int
    last_active_at: datetime | None


@dataclass
class MetricRow:
    """The pilot-metrics columns adoption math consumes, as plain data."""

    clinician_id: uuid.UUID
    template_section_completeness: float | None
    citation_traceability_rate: float | None
    physician_edit_rate_json: str | None
    stage1_latency_ms: int | None
    stage2_latency_ms: int | None


def parse_edit_rate(raw: str | None) -> float | None:
    """Mean of the per-section edit-rate dict, mirroring the
    ``/admin/metrics`` parsing (a bare number is accepted too)."""
    if not raw:
        return None
    try:
        rates = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(rates, dict) and rates:
        values = [v for v in rates.values() if isinstance(v, (int, float))]
        return (sum(values) / len(values)) if values else None
    if isinstance(rates, (int, float)):
        return float(rates)
    return None


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _time_saved(exported: int, baseline: float | None) -> float | None:
    """Explicit-assumption estimate: minutes saved = exported notes ×
    caller-supplied baseline. None when no baseline was given — we never
    invent the assumption server-side."""
    if baseline is None:
        return None
    return round(exported * baseline, 1)


def aggregate_adoption(
    session_aggs: list[SessionAgg],
    metric_rows: list[MetricRow],
    emails: dict[uuid.UUID, str],
    *,
    since: datetime | None,
    until: datetime | None,
    baseline_minutes_per_note: float | None,
) -> AdoptionResponse:
    """Join the per-clinician session aggregates with pilot-metrics quality
    averages into the adoption response. Pure — no DB access."""
    per_clinician_metrics: dict[uuid.UUID, dict[str, list[float]]] = {}
    for m in metric_rows:
        bucket = per_clinician_metrics.setdefault(
            m.clinician_id,
            {"comp": [], "cite": [], "edit": [], "s1": [], "s2": []},
        )
        if m.template_section_completeness is not None:
            bucket["comp"].append(m.template_section_completeness)
        if m.citation_traceability_rate is not None:
            bucket["cite"].append(m.citation_traceability_rate)
        edit = parse_edit_rate(m.physician_edit_rate_json)
        if edit is not None:
            bucket["edit"].append(edit)
        if m.stage1_latency_ms is not None:
            bucket["s1"].append(float(m.stage1_latency_ms))
        if m.stage2_latency_ms is not None:
            bucket["s2"].append(float(m.stage2_latency_ms))

    rows: list[ClinicianAdoptionRow] = []
    for agg in sorted(session_aggs, key=lambda a: a.sessions_total, reverse=True):
        quality = per_clinician_metrics.get(
            agg.clinician_id, {"comp": [], "cite": [], "edit": [], "s1": [], "s2": []}
        )
        rows.append(
            ClinicianAdoptionRow(
                clinician_id=str(agg.clinician_id),
                email=emails.get(agg.clinician_id),
                sessions_total=agg.sessions_total,
                sessions_exported=agg.sessions_exported,
                active_days=agg.active_days,
                notes_per_active_day=(
                    round(agg.sessions_exported / agg.active_days, 2)
                    if agg.active_days
                    else 0.0
                ),
                avg_completeness=_mean(quality["comp"]),
                avg_citation_traceability=_mean(quality["cite"]),
                avg_edit_rate=_mean(quality["edit"]),
                avg_stage1_latency_ms=_mean(quality["s1"]),
                avg_stage2_latency_ms=_mean(quality["s2"]),
                time_saved_minutes=_time_saved(
                    agg.sessions_exported, baseline_minutes_per_note
                ),
                last_active_at=(
                    agg.last_active_at.isoformat() if agg.last_active_at else None
                ),
            )
        )

    sessions_total = sum(a.sessions_total for a in session_aggs)
    sessions_exported = sum(a.sessions_exported for a in session_aggs)
    # Aggregate notes/active-day uses the SUM of per-clinician active days:
    # two clinicians each active the same 3 days = 6 clinician-days of
    # capacity, which is the denominator a per-day adoption average needs.
    total_active_days = sum(a.active_days for a in session_aggs)

    totals = AdoptionTotals(
        active_clinicians=sum(1 for a in session_aggs if a.sessions_total > 0),
        sessions_total=sessions_total,
        sessions_exported=sessions_exported,
        notes_per_active_day=(
            round(sessions_exported / total_active_days, 2)
            if total_active_days
            else 0.0
        ),
        avg_completeness=_mean(
            [m.template_section_completeness for m in metric_rows
             if m.template_section_completeness is not None]
        ),
        avg_citation_traceability=_mean(
            [m.citation_traceability_rate for m in metric_rows
             if m.citation_traceability_rate is not None]
        ),
        avg_edit_rate=_mean(
            [r for r in (parse_edit_rate(m.physician_edit_rate_json)
                         for m in metric_rows) if r is not None]
        ),
        avg_stage1_latency_ms=_mean(
            [float(m.stage1_latency_ms) for m in metric_rows
             if m.stage1_latency_ms is not None]
        ),
        avg_stage2_latency_ms=_mean(
            [float(m.stage2_latency_ms) for m in metric_rows
             if m.stage2_latency_ms is not None]
        ),
        time_saved_minutes=_time_saved(sessions_exported, baseline_minutes_per_note),
    )

    return AdoptionResponse(
        since=since,
        until=until,
        baseline_minutes_per_note=baseline_minutes_per_note,
        totals=totals,
        by_clinician=rows,
    )


_CSV_COLUMNS = [
    "clinician_id", "email", "sessions_total", "sessions_exported",
    "active_days", "notes_per_active_day", "avg_completeness",
    "avg_citation_traceability", "avg_edit_rate", "avg_stage1_latency_ms",
    "avg_stage2_latency_ms", "time_saved_minutes", "last_active_at",
]


def adoption_csv(resp: AdoptionResponse) -> str:
    """Per-clinician rows + a TOTAL footer row. Empty cells for nulls."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    for row in resp.by_clinician:
        d = row.model_dump()
        writer.writerow(["" if d[c] is None else d[c] for c in _CSV_COLUMNS])
    t = resp.totals
    writer.writerow([
        "TOTAL", "", t.sessions_total, t.sessions_exported, "",
        t.notes_per_active_day,
        "" if t.avg_completeness is None else t.avg_completeness,
        "" if t.avg_citation_traceability is None else t.avg_citation_traceability,
        "" if t.avg_edit_rate is None else t.avg_edit_rate,
        "" if t.avg_stage1_latency_ms is None else t.avg_stage1_latency_ms,
        "" if t.avg_stage2_latency_ms is None else t.avg_stage2_latency_ms,
        "" if t.time_saved_minutes is None else t.time_saved_minutes,
        "",
    ])
    return buf.getvalue()


# ── Route ────────────────────────────────────────────────────────────────────


@router.get("/analytics/adoption", response_model=AdoptionResponse)
async def get_adoption_analytics(
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    baseline_minutes_per_note: Optional[float] = Query(
        None,
        ge=0,
        le=120,
        description=(
            "Minutes of manual documentation assumed saved per exported "
            "note. Supplied by the caller so every time-saved figure is "
            "traceable to its assumption; omitted → time_saved is null."
        ),
    ),
    format: Literal["json", "csv"] = Query("json"),
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Adoption + ROI rollup, per-clinician and aggregate. EVAL_TEAM/ADMIN."""
    # Per-clinician session aggregate — one grouped query.
    s = SessionModel
    stmt = select(
        s.clinician_id,
        func.count().label("sessions_total"),
        func.sum(
            case((s.state.in_(_EXPORTED_STATES), 1), else_=0)
        ).label("sessions_exported"),
        func.count(func.distinct(func.date(s.created_at))).label("active_days"),
        func.max(s.created_at).label("last_active_at"),
    ).group_by(s.clinician_id)
    if since:
        stmt = stmt.where(s.created_at >= since)
    if until:
        stmt = stmt.where(s.created_at <= until)
    session_rows = (await db.execute(stmt)).all()
    session_aggs = [
        SessionAgg(
            clinician_id=r.clinician_id,
            sessions_total=r.sessions_total or 0,
            sessions_exported=int(r.sessions_exported or 0),
            active_days=r.active_days or 0,
            last_active_at=r.last_active_at,
        )
        for r in session_rows
    ]

    # Pilot-metrics rows in the window — parsed/averaged in Python because
    # edit-rate lives in a JSON column; pilot scale keeps this cheap.
    m = PilotMetricsModel
    mstmt = select(
        m.clinician_id,
        m.template_section_completeness,
        m.citation_traceability_rate,
        m.physician_edit_rate_json,
        m.stage1_latency_ms,
        m.stage2_latency_ms,
    )
    if since:
        mstmt = mstmt.where(m.created_at >= since)
    if until:
        mstmt = mstmt.where(m.created_at <= until)
    metric_rows = [
        MetricRow(
            clinician_id=r.clinician_id,
            template_section_completeness=r.template_section_completeness,
            citation_traceability_rate=r.citation_traceability_rate,
            physician_edit_rate_json=r.physician_edit_rate_json,
            stage1_latency_ms=r.stage1_latency_ms,
            stage2_latency_ms=r.stage2_latency_ms,
        )
        for r in (await db.execute(mstmt)).all()
    ]

    # Clinician emails for display — single IN query.
    ids = [a.clinician_id for a in session_aggs]
    emails: dict[uuid.UUID, str] = {}
    if ids:
        u = UserModel
        for r in (await db.execute(select(u.id, u.email).where(u.id.in_(ids)))).all():
            emails[r.id] = r.email

    resp = aggregate_adoption(
        session_aggs,
        metric_rows,
        emails,
        since=since,
        until=until,
        baseline_minutes_per_note=baseline_minutes_per_note,
    )

    if format == "csv":
        return Response(
            content=adoption_csv(resp),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="aurion_adoption.csv"'
            },
        )
    return resp
