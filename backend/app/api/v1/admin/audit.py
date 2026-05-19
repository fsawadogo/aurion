"""Audit log + PHI masking report endpoints — COMPLIANCE_OFFICER or ADMIN.

Both endpoints read from the append-only DynamoDB audit log. The masking
report is a roll-up over four specific event types; the audit endpoints
are pagination + filtering wrappers.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.v1.admin._shared import (
    AuditEventResponse,
    MaskingReportResponse,
    PaginatedAuditResponse,
    apply_audit_filters,
    event_to_response,
    scan_audit_events,
)
from app.core.types import UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit", response_model=PaginatedAuditResponse)
async def get_audit_log(
    clinician_id: Optional[str] = Query(None, description="Filter by clinician ID"),
    date_from: Optional[str] = Query(None, description="Filter from date (ISO format)"),
    date_to: Optional[str] = Query(None, description="Filter to date (ISO format)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """Paginated audit log with filters. COMPLIANCE_OFFICER or ADMIN."""
    audit = get_audit_log_service()

    if session_id:
        events = await audit.get_session_events(session_id)
    else:
        # DynamoDB scan — at pilot scale this is acceptable.
        # For production, add GSI on event_type + timestamp.
        events = await scan_audit_events(audit)

    filtered = apply_audit_filters(
        events,
        clinician_id=clinician_id,
        date_from=date_from,
        date_to=date_to,
        event_type=event_type,
    )

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    return PaginatedAuditResponse(
        items=[event_to_response(e) for e in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/audit/export")
async def export_audit_csv(
    clinician_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """Export audit events as CSV download. COMPLIANCE_OFFICER or ADMIN."""
    audit = get_audit_log_service()

    if session_id:
        events = await audit.get_session_events(session_id)
    else:
        events = await scan_audit_events(audit)

    filtered = apply_audit_filters(
        events,
        clinician_id=clinician_id,
        date_from=date_from,
        date_to=date_to,
        event_type=event_type,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["session_id", "event_timestamp", "event_type", "event_id", "details"])
    for evt in filtered:
        details = {
            k: v for k, v in evt.items()
            if k not in ("session_id", "event_timestamp", "event_type", "event_id")
        }
        writer.writerow([
            evt.get("session_id", ""),
            evt.get("event_timestamp", ""),
            evt.get("event_type", ""),
            evt.get("event_id", ""),
            json.dumps(details),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aurion_audit_log.csv"},
    )


@router.get("/audit/session/{session_id}", response_model=list[AuditEventResponse])
async def get_session_audit(
    session_id: str,
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """All audit events for a specific session. COMPLIANCE_OFFICER or ADMIN."""
    audit = get_audit_log_service()
    events = await audit.get_session_events(session_id)
    return [event_to_response(e) for e in events]


@router.get("/masking/report", response_model=MaskingReportResponse)
async def get_masking_report(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    clinician_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """Per-session masking report. COMPLIANCE_OFFICER or ADMIN.

    Per P0-02 acceptance: distinguishes masked / failed / skipped / uploaded
    counts per session. The report consumes four audit event types:

    - ``masking_confirmed`` — on-device masking succeeded for a frame.
    - ``masking_failed`` — on-device masking failed; the frame was
      quarantined (never uploaded). Counts toward `failed_frames`.
    - ``masking_failure_skipped`` — clinician explicitly skipped one or
      more quarantined frames. The event's `frame_count` is summed into
      `skipped_frames`.
    - ``frame_uploaded`` — backend received a frame with a valid masking
      proof; counts toward `uploaded_frames`.

    A session passes when no `masking_failed` events exist.
    """
    audit = get_audit_log_service()
    all_events = await scan_audit_events(audit)

    relevant_event_types = (
        "masking_confirmed",
        "masking_failed",
        "masking_failure_skipped",
        "frame_uploaded",
    )
    masking_events = [
        e for e in all_events if e.get("event_type") in relevant_event_types
    ]

    masking_events = apply_audit_filters(
        masking_events,
        clinician_id=clinician_id,
        date_from=date_from,
        date_to=date_to,
    )

    sessions_map: dict[str, dict[str, Any]] = {}
    for evt in masking_events:
        sid = evt.get("session_id", "")
        if sid not in sessions_map:
            sessions_map[sid] = {
                "session_id": sid,
                "clinician_name": evt.get("clinician_name", "Unknown"),
                "date": evt.get("event_timestamp", "")[:10],
                "total_frames": 0,
                "masked_frames": 0,
                "failed_frames": 0,
                "skipped_frames": 0,
                "uploaded_frames": 0,
                "pass": True,
            }
        bucket = sessions_map[sid]
        event_type = evt.get("event_type")
        if event_type == "masking_confirmed":
            bucket["masked_frames"] += 1
            bucket["total_frames"] += 1
        elif event_type == "masking_failed":
            bucket["failed_frames"] += 1
            bucket["total_frames"] += 1
            bucket["pass"] = False
        elif event_type == "masking_failure_skipped":
            # The mobile client emits one event covering N quarantined frames.
            try:
                count = int(evt.get("frame_count", 1))
            except (TypeError, ValueError):
                count = 1
            bucket["skipped_frames"] += count
        elif event_type == "frame_uploaded":
            bucket["uploaded_frames"] += 1

    sessions_list = list(sessions_map.values())
    pass_count = sum(1 for s in sessions_list if s["pass"])
    fail_count = len(sessions_list) - pass_count
    pass_rate = (pass_count / len(sessions_list) * 100) if sessions_list else 100.0

    return MaskingReportResponse(
        total_sessions=len(sessions_list),
        pass_count=pass_count,
        fail_count=fail_count,
        pass_rate=round(pass_rate, 1),
        sessions=sessions_list,
    )
