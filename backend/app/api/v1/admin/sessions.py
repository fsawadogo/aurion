"""Admin sessions list endpoint — EVAL_TEAM or ADMIN.

Paginated session listing with batched note-version + completeness
roll-up. Filters by clinician, specialty, state, date range.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404
from app.api.v1.admin._shared import (
    PaginatedSessionsResponse,
    SectionDetail,
    SessionAdminResponse,
    SessionDetailResponse,
    resolve_clinician_names,
)
from app.core.database import get_db
from app.core.models import SessionModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.note_gen import repository as note_repo
from app.modules.note_gen.service import get_template

router = APIRouter(prefix="/admin", tags=["admin"])


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

    # Batch-load latest note versions + clinician names in single queries
    # to avoid N+1 (one query per session in the loop).
    notes_by_session = await note_repo.get_latest_versions_by_session(
        db, (s.id for s in sessions)
    )
    names_by_id = await resolve_clinician_names(
        db, (s.clinician_id for s in sessions)
    )

    items = []
    for s in sessions:
        clinician_name = names_by_id[str(s.clinician_id)]

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


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_admin_session_detail(
    session_id: str,
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """One session's completeness with per-section breakdown. EVAL_TEAM or ADMIN.

    Returns the same shape as the list row plus a `sections` array that
    cross-references the specialty template against the latest note
    version. Sections required by the template but missing from the note
    are returned with status="not_captured" so the UI can highlight
    them as gaps.

    No claim text — only counts by source_type. Reviewers who need
    the full claim text use the eval interface, which surfaces masked
    content by design.
    """
    s = await get_session_or_404(db, session_id)
    name_map = await resolve_clinician_names(db, [s.clinician_id])
    clinician_name = name_map[str(s.clinician_id)]
    latest = await note_repo.get_latest_version(db, s.id)

    completeness_score = 0.0
    sections_populated = 0
    sections_required = 0
    provider_used = ""
    note_version = 0
    note_stage = 0
    is_approved = False
    note_sections_by_id: dict[str, dict] = {}

    if latest is not None:
        completeness_score = latest.completeness_score
        provider_used = latest.provider_used
        note_version = latest.version
        note_stage = latest.stage
        is_approved = latest.is_approved
        try:
            content = json.loads(latest.content)
            for sec in content.get("sections", []) or []:
                sid = sec.get("id")
                if isinstance(sid, str):
                    note_sections_by_id[sid] = sec
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        template = get_template(s.specialty)
        template_sections = template.sections
    except Exception:
        template_sections = []

    section_details: list[SectionDetail] = []
    for ts in template_sections:
        note_sec = note_sections_by_id.get(ts.id, {})
        claims = note_sec.get("claims", []) if isinstance(note_sec, dict) else []
        source_counts: dict[str, int] = {}
        for c in claims:
            if isinstance(c, dict):
                src = c.get("source_type") or "unknown"
                source_counts[src] = source_counts.get(src, 0) + 1
        section_details.append(SectionDetail(
            id=ts.id,
            title=ts.title,
            required=ts.required,
            status=note_sec.get("status", "not_captured") if note_sec else "not_captured",
            claims_count=len(claims),
            claim_sources=source_counts,
        ))

    if section_details:
        sections_required = sum(1 for d in section_details if d.required)
        sections_populated = sum(
            1 for d in section_details
            if d.required and d.status == "populated" and d.claims_count > 0
        )

    return SessionDetailResponse(
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
        note_version=note_version,
        note_stage=note_stage,
        is_approved=is_approved,
        sections=section_details,
    )
