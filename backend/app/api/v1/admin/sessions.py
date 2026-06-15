"""Admin sessions list endpoint — EVAL_TEAM or ADMIN.

Paginated session listing with batched note-version + completeness
roll-up. Filters by clinician, specialty, state, date range.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404, write_audit
from app.api.v1.admin._shared import (
    PaginatedSessionsResponse,
    SectionDetail,
    SessionAdminResponse,
    SessionDetailResponse,
    resolve_clinician_names,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import SessionModel
from app.core.types import Note, SessionState, UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.cleanup.service import purge_session_media
from app.modules.note_gen import repository as note_repo
from app.modules.note_gen.service import compute_session_stats, get_template
from app.modules.session.service import delete_session

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

        latest_note = notes_by_session.get(s.id)
        # lane-backend/empty-transcript-guard: roll all four stats through
        # ``compute_session_stats`` so the list endpoint, the detail
        # endpoint, and the recompute helper share one definition of
        # "populated". Before this PR the list endpoint counted any
        # section with ``status == "populated"`` regardless of whether
        # it had claims, while the detail endpoint required both — so
        # the same session could show different numbers on the same
        # page.
        note_obj: Note | None = None
        if latest_note is not None:
            try:
                content = json.loads(latest_note.content)
                note_obj = Note(**content)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Corrupt content — fall through to the "no note" zeros
                # so the dashboard surfaces the bad row honestly rather
                # than echoing the stale stored completeness_score.
                note_obj = None

        try:
            template = get_template(s.specialty)
        except Exception:
            template = None

        if note_obj is not None and template is not None:
            (
                completeness_score,
                sections_populated,
                sections_required,
                provider_used,
            ) = compute_session_stats(note_obj, template)
        else:
            completeness_score = 0.0
            sections_populated = 0
            sections_required = (
                sum(1 for ts in template.sections if ts.required)
                if template is not None
                else 0
            )
            provider_used = ""

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
    session_id: uuid.UUID,
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

    note_version = 0
    note_stage = 0
    is_approved = False
    note_sections_by_id: dict[str, dict] = {}
    note_obj: Note | None = None

    if latest is not None:
        note_version = latest.version
        note_stage = latest.stage
        is_approved = latest.is_approved
        try:
            content = json.loads(latest.content)
            for sec in content.get("sections", []) or []:
                sid = sec.get("id")
                if isinstance(sid, str):
                    note_sections_by_id[sid] = sec
            # Round-trip into the pydantic model so ``compute_session_stats``
            # gets the same honest definition the scorer would. A corrupt
            # row falls through to ``note_obj=None`` and the empty-note
            # zeros, matching the list-endpoint behavior.
            try:
                note_obj = Note(**content)
            except (TypeError, ValueError):
                note_obj = None
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        template = get_template(s.specialty)
        template_sections = template.sections
    except Exception:
        template = None
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

    # lane-backend/empty-transcript-guard: roll the headline four stats
    # through ``compute_session_stats`` so this endpoint and the list
    # endpoint can never disagree on what "populated" means.
    if note_obj is not None and template is not None:
        (
            completeness_score,
            sections_populated,
            sections_required,
            provider_used,
        ) = compute_session_stats(note_obj, template)
    else:
        completeness_score = 0.0
        sections_populated = 0
        sections_required = sum(1 for d in section_details if d.required)
        provider_used = ""

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


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_session(
    session_id: uuid.UUID,
    actor: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete ANY clinician's session and its data. ADMIN only.

    The compliance/admin counterpart to the clinician self-service
    `DELETE /sessions/{id}` (which is owner-scoped). Used from the
    Captured Media admin view to purge a session a clinician can't reach.

    Removes the session plus its child rows (transcript / note-version /
    pilot-metric / stage-2) AND purges the raw S3 media (audio / frames /
    clips) so nothing lingers until the retention TTL. The DynamoDB audit
    trail is append-only and is NOT erased: an `admin_session_deleted`
    event (carrying the prior state + the target clinician) is written
    after the delete commits, so the record of who deleted what survives.
    """
    session = await get_session_or_404(db, session_id)
    prior_state = (
        session.state.value
        if isinstance(session.state, SessionState)
        else str(session.state)
    )
    target_clinician_id = str(session.clinician_id)

    await delete_session(db, session)
    await db.commit()

    # Purge the raw media bytes. Best-effort + fail-soft (purge_session_media
    # already swallows per-step errors): the DB delete is the source of truth
    # for the session disappearing from the Captured Media list; orphaned
    # media would otherwise age out via the S3 retention TTL anyway.
    await purge_session_media(str(session_id))

    await write_audit(
        session_id,
        AuditEventType.ADMIN_SESSION_DELETED,
        prior_state=prior_state,
        target_clinician_id=target_clinician_id,
    )
