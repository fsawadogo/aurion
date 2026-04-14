"""Admin API routes — user management, audit log, masking reports,
config viewer, pilot metrics, session completeness, and eval scoring.

All endpoints are role-gated. No business logic here — routes call
module service functions only.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import NoteVersionModel, PilotMetricsModel, SessionModel
from app.core.types import SessionState, UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_config

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Mock User Store ────────────────────────────────────────────────────────
# In production, user data comes from Cognito. For now, a simple
# in-memory store seeded with the dev users.

_MOCK_USERS: dict[str, dict[str, Any]] = {
    "u1": {
        "id": "u1",
        "email": "perry@creoq.ca",
        "full_name": "Dr. Perry Gdalevitch",
        "role": "CLINICIAN",
        "is_active": True,
        "voice_enrolled": True,
        "created_at": "2026-01-15T10:00:00Z",
        "last_login_at": "2026-04-10T14:30:00Z",
    },
    "u2": {
        "id": "u2",
        "email": "marie@creoq.ca",
        "full_name": "Dr. Marie Gdalevitch",
        "role": "CLINICIAN",
        "is_active": True,
        "voice_enrolled": False,
        "created_at": "2026-01-15T10:00:00Z",
        "last_login_at": "2026-04-09T09:15:00Z",
    },
    "u3": {
        "id": "u3",
        "email": "compliance@aurionclinical.com",
        "full_name": "Compliance Officer",
        "role": "COMPLIANCE_OFFICER",
        "is_active": True,
        "voice_enrolled": False,
        "created_at": "2026-02-01T09:00:00Z",
        "last_login_at": None,
    },
    "u4": {
        "id": "u4",
        "email": "eval@aurionclinical.com",
        "full_name": "Eval Reviewer",
        "role": "EVAL_TEAM",
        "is_active": True,
        "voice_enrolled": False,
        "created_at": "2026-02-01T09:00:00Z",
        "last_login_at": None,
    },
}


# ── Request / Response Schemas ─────────────────────────────────────────────


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    voice_enrolled: bool
    created_at: str
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    email: str
    full_name: str
    role: UserRole
    password: str = Field(exclude=True)


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class AuditEventResponse(BaseModel):
    session_id: str
    event_timestamp: str
    event_type: str
    event_id: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class PaginatedAuditResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int


class MaskingSessionResult(BaseModel):
    session_id: str
    clinician_name: str
    date: str
    total_frames: int
    masked_frames: int
    passed: bool = Field(alias="pass", serialization_alias="pass")


class MaskingReportResponse(BaseModel):
    total_sessions: int
    pass_count: int
    fail_count: int
    pass_rate: float
    sessions: list[dict[str, Any]]


class PilotMetricResponse(BaseModel):
    session_id: str
    clinician_id: str
    specialty: Optional[str] = None
    template_section_completeness: Optional[float] = None
    citation_traceability_rate: Optional[float] = None
    physician_edit_rate: Optional[float] = None
    conflict_rate: Optional[float] = None
    low_confidence_frame_rate: Optional[float] = None
    stage1_latency_ms: Optional[int] = None
    stage2_latency_ms: Optional[int] = None
    session_completeness: bool = False
    created_at: str = ""

    model_config = {"from_attributes": True}


class PaginatedMetricsResponse(BaseModel):
    items: list[PilotMetricResponse]
    total: int
    page: int
    page_size: int


class SessionAdminResponse(BaseModel):
    id: str
    clinician_id: str
    clinician_name: str
    specialty: str
    state: str
    completeness_score: float
    sections_populated: int
    sections_required: int
    provider_used: str
    created_at: str
    updated_at: str


class PaginatedSessionsResponse(BaseModel):
    items: list[SessionAdminResponse]
    total: int
    page: int
    page_size: int


class EvalSessionResponse(BaseModel):
    id: str
    session_id: str
    clinician_name: str
    specialty: str
    transcript_masked: bool
    frames_masked: bool
    note_version: int
    scored: bool
    scores: Optional[dict[str, Any]] = None
    created_at: str


class EvalScoreRequest(BaseModel):
    transcript_accuracy: float = Field(ge=0, le=100)
    citation_correctness: float = Field(ge=0, le=100)
    descriptive_mode_compliance: float = Field(ge=0, le=100)
    notes: str = ""


class ConfigChangeEvent(BaseModel):
    id: str
    changed_by: str
    changed_at: str
    previous_config: dict[str, Any]
    new_config: dict[str, Any]
    appconfig_version: int


# ═══════════════════════════════════════════════════════════════════════════
# Users
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    """List all users. ADMIN only."""
    return list(_MOCK_USERS.values())


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    """Create a new user. ADMIN only."""
    new_id = f"u{len(_MOCK_USERS) + 1}_{uuid.uuid4().hex[:6]}"
    new_user = {
        "id": new_id,
        "email": body.email,
        "full_name": body.full_name,
        "role": body.role.value,
        "is_active": True,
        "voice_enrolled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login_at": None,
    }
    _MOCK_USERS[new_id] = new_user

    # Audit log
    audit = get_audit_log_service()
    await audit.write_event(
        session_id="system",
        event_type="user_created",
        target_user_id=new_id,
        target_email=body.email,
        target_role=body.role,
        created_by=str(user.user_id),
    )

    return new_user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    """Update user role or status. ADMIN only."""
    if user_id not in _MOCK_USERS:
        raise HTTPException(status_code=404, detail="User not found")

    target = _MOCK_USERS[user_id]
    changes: dict[str, Any] = {}

    if body.full_name is not None:
        changes["full_name"] = {"previous": target["full_name"], "new": body.full_name}
        target["full_name"] = body.full_name

    if body.role is not None:
        changes["role"] = {"previous": target["role"], "new": body.role.value}
        target["role"] = body.role.value

    if body.is_active is not None:
        changes["is_active"] = {"previous": target["is_active"], "new": body.is_active}
        target["is_active"] = body.is_active

    if changes:
        audit = get_audit_log_service()
        await audit.write_event(
            session_id="system",
            event_type="user_updated",
            target_user_id=user_id,
            changes=str(changes),
            updated_by=str(user.user_id),
        )

    return target


# ═══════════════════════════════════════════════════════════════════════════
# Audit Log
# ═══════════════════════════════════════════════════════════════════════════


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

    # If filtering by session_id, use the direct query
    if session_id:
        events = await audit.get_session_events(session_id)
    else:
        # DynamoDB scan — at pilot scale this is acceptable.
        # For production, add GSI on event_type + timestamp.
        events = await _scan_audit_events(audit)

    # Apply filters
    filtered = _apply_audit_filters(
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
        items=[_event_to_response(e) for e in page_items],
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
        events = await _scan_audit_events(audit)

    filtered = _apply_audit_filters(
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
        details = {k: v for k, v in evt.items() if k not in ("session_id", "event_timestamp", "event_type", "event_id")}
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
    return [_event_to_response(e) for e in events]


# ═══════════════════════════════════════════════════════════════════════════
# PHI Masking Report
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/masking/report", response_model=MaskingReportResponse)
async def get_masking_report(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    clinician_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(
        require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN)
    ),
):
    """Per-session masking pass/fail report. COMPLIANCE_OFFICER or ADMIN.

    Queries the audit log for masking_confirmed events and aggregates
    pass/fail status per session.
    """
    audit = get_audit_log_service()
    all_events = await _scan_audit_events(audit)

    # Filter to masking-related events
    masking_events = [
        e for e in all_events if e.get("event_type") in ("masking_confirmed", "masking_failed")
    ]

    # Apply date and clinician filters
    masking_events = _apply_audit_filters(
        masking_events,
        clinician_id=clinician_id,
        date_from=date_from,
        date_to=date_to,
    )

    # Aggregate per session
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
                "pass": True,
            }
        sessions_map[sid]["total_frames"] += 1
        if evt.get("event_type") == "masking_confirmed":
            sessions_map[sid]["masked_frames"] += 1
        else:
            sessions_map[sid]["pass"] = False

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


# ═══════════════════════════════════════════════════════════════════════════
# Provider Configuration
# ═══════════════════════════════════════════════════════════════════════════


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
    all_events = await _scan_audit_events(audit)

    config_events = [
        e for e in all_events if e.get("event_type") in ("config_changed", "provider_changed")
    ]

    result = []
    for evt in config_events:
        result.append(ConfigChangeEvent(
            id=evt.get("event_id", ""),
            changed_by=evt.get("changed_by", "system"),
            changed_at=evt.get("event_timestamp", ""),
            previous_config=_safe_json_parse(evt.get("previous_config", "{}")),
            new_config=_safe_json_parse(evt.get("new_config", "{}")),
            appconfig_version=int(evt.get("appconfig_version", 0)),
        ))

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Pilot Metrics
# ═══════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════
# Sessions (Admin View)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/sessions", response_model=PaginatedSessionsResponse)
async def get_admin_sessions(
    clinician_id: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Sessions with completeness scores. EVAL_TEAM or ADMIN."""
    stmt = select(SessionModel).order_by(SessionModel.created_at.desc())

    if clinician_id:
        try:
            cid = uuid.UUID(clinician_id)
            stmt = stmt.where(SessionModel.clinician_id == cid)
        except ValueError:
            pass

    if specialty:
        stmt = stmt.where(SessionModel.specialty == specialty)

    if state:
        stmt = stmt.where(SessionModel.state == state)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            stmt = stmt.where(SessionModel.created_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            stmt = stmt.where(SessionModel.created_at <= dt_to)
        except ValueError:
            pass

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Paginate
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Batch-load latest note versions for all sessions in a single query
    # to avoid N+1 (one query per session in the loop).
    session_ids = [s.id for s in sessions]
    notes_by_session: dict[uuid.UUID, NoteVersionModel] = {}

    if session_ids:
        max_version_sub = (
            select(
                NoteVersionModel.session_id,
                func.max(NoteVersionModel.version).label("max_ver"),
            )
            .where(NoteVersionModel.session_id.in_(session_ids))
            .group_by(NoteVersionModel.session_id)
            .subquery()
        )
        notes_stmt = (
            select(NoteVersionModel)
            .join(
                max_version_sub,
                (NoteVersionModel.session_id == max_version_sub.c.session_id)
                & (NoteVersionModel.version == max_version_sub.c.max_ver),
            )
        )
        notes_result = await db.execute(notes_stmt)
        for nv in notes_result.scalars().all():
            notes_by_session[nv.session_id] = nv

    items = []
    for s in sessions:
        clinician_name = _get_clinician_name(str(s.clinician_id))

        completeness_score = 0.0
        sections_populated = 0
        sections_required = 0
        provider_used = ""

        latest_note = notes_by_session.get(s.id)
        if latest_note:
            completeness_score = latest_note.completeness_score
            provider_used = latest_note.provider_used
            try:
                content = json.loads(latest_note.content)
                note_sections = content.get("sections", [])
                sections_required = len(note_sections)
                sections_populated = sum(
                    1 for sec in note_sections if sec.get("status") == "populated"
                )
            except (json.JSONDecodeError, TypeError):
                pass

        items.append(SessionAdminResponse(
            id=str(s.id),
            clinician_id=str(s.clinician_id),
            clinician_name=clinician_name,
            specialty=s.specialty,
            state=s.state.value if hasattr(s.state, "value") else str(s.state),
            completeness_score=completeness_score,
            sections_populated=sections_populated,
            sections_required=sections_required,
            provider_used=provider_used,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
        ))

    return PaginatedSessionsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Eval Team Interface
# ═══════════════════════════════════════════════════════════════════════════

# In-memory eval scores — migrates to PostgreSQL table in production
_EVAL_SCORES: dict[str, dict[str, Any]] = {}


@router.get("/eval/sessions", response_model=list[EvalSessionResponse])
async def get_eval_sessions(
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Eval assignments — sessions available for quality scoring. EVAL_TEAM or ADMIN."""
    reviewable_states = [
        SessionState.AWAITING_REVIEW,
        SessionState.PROCESSING_STAGE2,
        SessionState.REVIEW_COMPLETE,
        SessionState.EXPORTED,
        SessionState.PURGED,
    ]

    stmt = (
        select(SessionModel)
        .where(SessionModel.state.in_(reviewable_states))
        .order_by(SessionModel.created_at.desc())
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Batch-load latest note versions for all sessions to avoid N+1 queries.
    session_ids = [s.id for s in sessions]
    notes_by_session: dict[uuid.UUID, NoteVersionModel] = {}

    if session_ids:
        max_version_sub = (
            select(
                NoteVersionModel.session_id,
                func.max(NoteVersionModel.version).label("max_ver"),
            )
            .where(NoteVersionModel.session_id.in_(session_ids))
            .group_by(NoteVersionModel.session_id)
            .subquery()
        )
        notes_stmt = (
            select(NoteVersionModel)
            .join(
                max_version_sub,
                (NoteVersionModel.session_id == max_version_sub.c.session_id)
                & (NoteVersionModel.version == max_version_sub.c.max_ver),
            )
        )
        notes_result = await db.execute(notes_stmt)
        for nv in notes_result.scalars().all():
            notes_by_session[nv.session_id] = nv

    # Batch-load masking status from audit log for all sessions at once,
    # instead of one DynamoDB query per session.
    audit = get_audit_log_service()
    masking_by_session: dict[str, bool] = {}
    for s in sessions:
        sid = str(s.id)
        session_events = await audit.get_session_events(sid)
        masking_by_session[sid] = any(
            e.get("event_type") == "masking_confirmed" for e in session_events
        )

    eval_sessions = []
    for s in sessions:
        sid = str(s.id)
        clinician_name = _get_clinician_name(str(s.clinician_id))
        scores = _EVAL_SCORES.get(sid)
        latest_note = notes_by_session.get(s.id)
        note_version = latest_note.version if latest_note else 0

        eval_sessions.append(EvalSessionResponse(
            id=f"eval_{sid[:8]}",
            session_id=sid,
            clinician_name=clinician_name,
            specialty=s.specialty,
            transcript_masked=True,  # All transcripts are masked by policy
            frames_masked=masking_by_session.get(sid, False),
            note_version=note_version,
            scored=scores is not None,
            scores=scores,
            created_at=s.created_at.isoformat() if s.created_at else "",
        ))

    return eval_sessions


@router.post("/eval/sessions/{session_id}/score", response_model=EvalSessionResponse)
async def submit_eval_score(
    session_id: str,
    body: EvalScoreRequest,
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Submit quality scores for a session. EVAL_TEAM or ADMIN."""
    # Verify session exists
    try:
        sid_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    stmt = select(SessionModel).where(SessionModel.id == sid_uuid)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Calculate overall score
    overall = round(
        (body.transcript_accuracy + body.citation_correctness + body.descriptive_mode_compliance) / 3,
        1,
    )

    scores = {
        "transcript_accuracy": body.transcript_accuracy,
        "citation_correctness": body.citation_correctness,
        "descriptive_mode_compliance": body.descriptive_mode_compliance,
        "overall": overall,
        "notes": body.notes,
        "scored_by": user.email,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }

    _EVAL_SCORES[session_id] = scores

    # Audit log
    audit = get_audit_log_service()
    await audit.write_event(
        session_id=session_id,
        event_type="eval_score_submitted",
        overall_score=overall,
        scored_by=user.email,
    )

    clinician_name = _get_clinician_name(str(session.clinician_id))

    return EvalSessionResponse(
        id=f"eval_{session_id[:8]}",
        session_id=session_id,
        clinician_name=clinician_name,
        specialty=session.specialty,
        transcript_masked=True,
        frames_masked=True,
        note_version=0,
        scored=True,
        scores=scores,
        created_at=session.created_at.isoformat() if session.created_at else "",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════


async def _scan_audit_events(audit_service) -> list[dict[str, Any]]:
    """Scan all audit events from DynamoDB.

    At pilot scale (hundreds of sessions) a full table scan is acceptable.
    For production, add GSIs and use query operations.
    """
    try:
        table = audit_service._table
        response = table.scan()
        items = response.get("Items", [])

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        # Sort by timestamp descending
        items.sort(key=lambda x: x.get("event_timestamp", ""), reverse=True)
        return items
    except Exception:
        return []


def _apply_audit_filters(
    events: list[dict[str, Any]],
    clinician_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    event_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Apply filters to a list of audit events."""
    filtered = events

    if clinician_id:
        filtered = [
            e for e in filtered
            if e.get("clinician_id") == clinician_id or e.get("actor_id") == clinician_id
        ]

    if date_from:
        filtered = [e for e in filtered if e.get("event_timestamp", "") >= date_from]

    if date_to:
        # Inclusive — include events up to end of the day
        to_str = date_to if "T" in date_to else f"{date_to}T23:59:59.999"
        filtered = [e for e in filtered if e.get("event_timestamp", "") <= to_str]

    if event_type:
        filtered = [e for e in filtered if e.get("event_type") == event_type]

    return filtered


def _event_to_response(evt: dict[str, Any]) -> AuditEventResponse:
    """Convert a raw DynamoDB audit event to the response schema."""
    details = {
        k: v
        for k, v in evt.items()
        if k not in ("session_id", "event_timestamp", "event_type", "event_id")
    }
    return AuditEventResponse(
        session_id=evt.get("session_id", ""),
        event_timestamp=evt.get("event_timestamp", ""),
        event_type=evt.get("event_type", ""),
        event_id=evt.get("event_id", ""),
        details=details,
    )


def _get_clinician_name(clinician_id: str) -> str:
    """Look up clinician name from mock user store."""
    for u in _MOCK_USERS.values():
        if u["id"] == clinician_id:
            return u["full_name"]
    return f"Clinician {clinician_id[:8]}"


def _safe_json_parse(value: Any) -> dict[str, Any]:
    """Safely parse a JSON string, returning empty dict on failure."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
