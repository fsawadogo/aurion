"""Compliance reporting endpoints (issue #77 foundation).

Persisted, sha256-signed report snapshots. POST triggers, GET lists / fetches
metadata, /download streams the bytes with the hash echoed in a header so
the recipient can verify.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin._shared import scan_audit_events
from app.core.database import get_db
from app.core.types import UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, require_role
from app.modules.compliance.reports_service import (
    ComplianceReportsService,
    ReportType,
    get_compliance_reports_service,
)

router = APIRouter(prefix="/admin", tags=["admin"])


_ROLES = (UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)


class GenerateReportRequest(BaseModel):
    report_type: ReportType = Field(
        ..., description="One of: audit, masking, retention (all wired, #407)."
    )
    since: datetime | None = None
    until: datetime | None = None


class ReportMetadataResponse(BaseModel):
    id: uuid.UUID
    report_type: str
    since: datetime | None
    until: datetime | None
    generated_at: datetime
    generated_by: uuid.UUID | None
    sha256: str
    byte_size: int


class ReportListResponse(BaseModel):
    items: list[ReportMetadataResponse]
    limit: int
    offset: int


def _to_metadata(record) -> ReportMetadataResponse:
    return ReportMetadataResponse(
        id=record.id,
        report_type=record.report_type,
        since=record.since,
        until=record.until,
        generated_at=record.generated_at,
        generated_by=record.generated_by,
        sha256=record.sha256,
        byte_size=record.byte_size,
    )


@router.post(
    "/compliance/reports",
    response_model=ReportMetadataResponse,
    status_code=201,
)
async def generate_report(
    body: GenerateReportRequest,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
    service: ComplianceReportsService = Depends(get_compliance_reports_service),
) -> ReportMetadataResponse:
    """Trigger a new compliance report snapshot."""
    audit = get_audit_log_service()
    events = await scan_audit_events(audit)
    try:
        record = await service.generate(
            db,
            report_type=body.report_type,
            events=events,
            since=body.since,
            until=body.until,
            generated_by=user.user_id,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_metadata(record)


@router.get(
    "/compliance/reports",
    response_model=ReportListResponse,
)
async def list_reports(
    report_type: Optional[ReportType] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
    service: ComplianceReportsService = Depends(get_compliance_reports_service),
) -> ReportListResponse:
    records = await service.list(
        db, report_type=report_type, limit=limit, offset=offset
    )
    return ReportListResponse(
        items=[_to_metadata(r) for r in records],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/compliance/reports/{report_id}",
    response_model=ReportMetadataResponse,
)
async def get_report(
    report_id: uuid.UUID,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
    service: ComplianceReportsService = Depends(get_compliance_reports_service),
) -> ReportMetadataResponse:
    record = await service.get(db, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _to_metadata(record)


@router.get("/compliance/reports/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
    service: ComplianceReportsService = Depends(get_compliance_reports_service),
) -> StreamingResponse:
    """Stream the persisted CSV bytes. ``X-Aurion-Sha256`` echoes the hash
    so the recipient can verify the file on disk matches the metadata."""
    record = await service.get(db, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return StreamingResponse(
        iter([record.content_bytes]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=aurion_{record.report_type}_"
                f"{record.id}.csv"
            ),
            "X-Aurion-Sha256": record.sha256,
            "X-Aurion-Byte-Size": str(record.byte_size),
        },
    )
