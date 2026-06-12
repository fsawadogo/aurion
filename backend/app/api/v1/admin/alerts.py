"""Operational alerts — paginated list (issue #76 foundation).

Trigger sites (Stage failures, masking issues, SLA breaches) publish to
the ``alerts`` table via ``AlertService``. ADMIN + COMPLIANCE_OFFICER
read and acknowledge here (#76). Delivery sinks (Slack/email) land as
follow-ups — the email leg is now UNBLOCKED (email moved off SES to
Resend; see app/core/email_sender.py) and can call
``core.email_sender.send_email`` directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import UserRole
from app.modules.alerts.service import (
    AlertService,
    AlertSeverity,
    get_alert_service,
)
from app.modules.auth.service import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


class AlertResponse(BaseModel):
    id: uuid.UUID
    alert_type: str
    severity: str
    source: str
    message: str
    metadata: dict[str, Any] | None
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: uuid.UUID | None


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    limit: int
    offset: int


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    status: Optional[str] = Query(
        None,
        pattern="^(open|acknowledged)$",
        description="Filter by ack state.",
    ),
    severity: Optional[AlertSeverity] = Query(
        None, description="Filter by severity."
    ),
    alert_type: Optional[str] = Query(
        None, max_length=64, description="Filter by alert_type exact match."
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
    db: AsyncSession = Depends(get_db),
    service: AlertService = Depends(get_alert_service),
) -> AlertListResponse:
    """Paginated list of alerts, newest first."""
    records = await service.list(
        db,
        status=status,
        severity=severity,
        alert_type=alert_type,
        limit=limit,
        offset=offset,
    )
    items = [
        AlertResponse(
            id=r.id,
            alert_type=r.alert_type,
            severity=r.severity,
            source=r.source,
            message=r.message,
            metadata=r.alert_metadata,
            created_at=r.created_at,
            acknowledged_at=r.acknowledged_at,
            acknowledged_by=r.acknowledged_by,
        )
        for r in records
    ]
    return AlertListResponse(items=items, limit=limit, offset=offset)


@router.patch("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
    db: AsyncSession = Depends(get_db),
    service: AlertService = Depends(get_alert_service),
) -> AlertResponse:
    """Acknowledge an alert (#76). Idempotent — re-acknowledging returns
    the row unchanged, preserving the first acknowledger."""
    row = await service.acknowledge(db, alert_id, acknowledged_by=user.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertResponse(
        id=row.id,
        alert_type=row.alert_type,
        severity=row.severity,
        source=row.source,
        message=row.message,
        metadata=row.alert_metadata,
        created_at=row.created_at,
        acknowledged_at=row.acknowledged_at,
        acknowledged_by=row.acknowledged_by,
    )
