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

from app.api.v1.admin._shared import (
    PaginatedSessionsResponse,
    SessionAdminResponse,
    get_clinician_name,
)
from app.core.database import get_db
from app.core.models import SessionModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.note_gen import repository as note_repo

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

    # Batch-load latest note versions for all sessions in a single query
    # to avoid N+1 (one query per session in the loop).
    notes_by_session = await note_repo.get_latest_versions_by_session(
        db, (s.id for s in sessions)
    )

    items = []
    for s in sessions:
        clinician_name = get_clinician_name(str(s.clinician_id))

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
