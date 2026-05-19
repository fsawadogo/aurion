"""Pilot metrics + provider configuration viewer.

Pilot metrics: paginated read of ``pilot_metrics`` rows with filters.
EVAL_TEAM or ADMIN.

Provider configuration: read-only AppConfig snapshot + config change
history (audit-derived). COMPLIANCE_OFFICER or ADMIN.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin._shared import (
    ConfigChangeEvent,
    PaginatedMetricsResponse,
    PilotMetricResponse,
    safe_json_parse,
    scan_audit_events,
)
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
            created_at=row.created_at.isoformat() if row.created_at else "",
        ))

    return PaginatedMetricsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
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
