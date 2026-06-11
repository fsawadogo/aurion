"""Eval team interface — list reviewable sessions and submit quality scores.

EVAL_TEAM or ADMIN. Scores persist in the ``eval_scores`` table (B-08).
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404, write_audit
from app.api.v1.admin._shared import (
    EvalAssigneeResponse,
    EvalAssignmentRequest,
    EvalScoreRequest,
    EvalSessionDetailResponse,
    EvalSessionResponse,
    EvalTranscriptSegment,
    resolve_clinician_names,
    scan_audit_events,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import EvalScoreModel, SessionModel, TranscriptModel
from app.core.types import SessionState, UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth import users_repository as users_repo
from app.modules.auth.service import CurrentUser, require_role
from app.modules.eval import repository as eval_repo
from app.modules.note_gen import repository as note_repo

router = APIRouter(prefix="/admin", tags=["admin"])


def _score_payload(row: EvalScoreModel) -> dict:
    """Serialize an EvalScoreModel into the response dict shape.

    Legacy three-slider fields plus the spec-aligned columns added in
    migration 0004 (nullable — appear in the payload as None for rows
    that predate slice 2 of the eval triad work).
    """
    return {
        "transcript_accuracy": row.transcript_accuracy,
        "citation_correctness": row.citation_correctness,
        "descriptive_mode_compliance": row.descriptive_mode_compliance,
        "overall": row.overall,
        "notes": row.notes,
        "scored_by": row.scored_by,
        "scored_at": row.scored_at.isoformat() if row.scored_at else "",
        "descriptive_mode_pass": row.descriptive_mode_pass,
        "soap_section_scores": row.soap_section_scores,
        "hallucination_count": row.hallucination_count,
        "discrepancies": row.discrepancies,
    }


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

    # EVAL-3 role-aware filtering: EVAL_TEAM users only see sessions
    # assigned to them. ADMIN sees everything (assignment view shown as
    # a read-only column).
    if user.role == UserRole.EVAL_TEAM:
        assigned_sids = await eval_repo.get_session_ids_assigned_to(
            db, user.user_id
        )
        if not assigned_sids:
            return []
        stmt = stmt.where(SessionModel.id.in_(assigned_sids))

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Batch-load notes, clinician names, eval scores, and assignments
    # in single queries (one round-trip per concern).
    notes_by_session = await note_repo.get_latest_versions_by_session(
        db, (s.id for s in sessions)
    )
    names_by_id = await resolve_clinician_names(
        db, (s.clinician_id for s in sessions)
    )
    scores_by_session = await eval_repo.get_scores_by_sessions(
        db, (s.id for s in sessions)
    )
    assignments_by_session = await eval_repo.get_assignments_by_sessions(
        db, (s.id for s in sessions)
    )

    # One DynamoDB scan instead of N per-session queries — pilot scale
    # makes the trade safe and the in-memory filter cheaper than the
    # round-trips the prior loop incurred.
    audit = get_audit_log_service()
    all_events = await scan_audit_events(audit)
    sessions_with_masking_confirmed = {
        e.get("session_id", "")
        for e in all_events
        if e.get("event_type") == "masking_confirmed"
    }

    eval_sessions = []
    for s in sessions:
        sid = str(s.id)
        clinician_name = names_by_id[str(s.clinician_id)]
        score_row = scores_by_session.get(s.id)
        latest_note = notes_by_session.get(s.id)
        note_version = latest_note.version if latest_note else 0
        assignment = assignments_by_session.get(s.id)

        eval_sessions.append(EvalSessionResponse(
            id=f"eval_{sid[:8]}",
            session_id=sid,
            clinician_name=clinician_name,
            specialty=s.specialty,
            transcript_masked=True,  # All transcripts are masked by policy
            frames_masked=sid in sessions_with_masking_confirmed,
            note_version=note_version,
            scored=score_row is not None,
            scores=_score_payload(score_row) if score_row else None,
            created_at=s.created_at.isoformat() if s.created_at else "",
            assigned_to=assignment.assignee_email if assignment else None,
            assignment_completed_at=(
                assignment.completed_at.isoformat()
                if assignment and assignment.completed_at
                else None
            ),
        ))

    return eval_sessions


@router.get("/eval/sessions/{session_id}", response_model=EvalSessionDetailResponse)
async def get_eval_session_detail(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Triad view for one session — masked transcript + note (with claims
    that anchor to transcript segments + frame ids) + score state.

    EVAL_TEAM or ADMIN. The shape is additive over EvalSessionResponse —
    the frontend list page can keep using the smaller list response,
    only the detail route needs this fatter payload.
    """
    # FastAPI validates the uuid.UUID path param → a malformed id returns a
    # CORS-bearing 422 before we get here (matches sessions/media/users).
    sid_uuid = session_id

    s = await get_session_or_404(db, sid_uuid)
    sid = str(s.id)

    names = await resolve_clinician_names(db, [s.clinician_id])
    clinician_name = names[str(s.clinician_id)]

    # Masking-confirmed lookup mirrors the list endpoint — single audit
    # scan, in-memory filter.
    audit = get_audit_log_service()
    all_events = await scan_audit_events(audit)
    frames_masked = any(
        e.get("event_type") == "masking_confirmed" and e.get("session_id") == sid
        for e in all_events
    )

    score_row = await eval_repo.get_score(db, sid_uuid)
    latest_note = await note_repo.get_latest_version(db, sid_uuid)
    assignment = await eval_repo.get_assignment(db, sid_uuid)

    # If the caller is EVAL_TEAM and not the assignee, hide the session
    # (404 — the URL doesn't exist as far as they're concerned).
    if (
        user.role == UserRole.EVAL_TEAM
        and (assignment is None or assignment.assignee_user_id != user.user_id)
    ):
        raise HTTPException(status_code=404, detail="Session not found")

    # Transcript — one row per session.
    transcript_segments: list[EvalTranscriptSegment] = []
    transcript_provider = ""
    transcript_row = await db.get(TranscriptModel, sid_uuid)
    if transcript_row is not None:
        transcript_provider = transcript_row.provider_used
        try:
            parsed = json.loads(transcript_row.transcript_json)
            for seg in parsed.get("segments", []) or []:
                if not isinstance(seg, dict):
                    continue
                transcript_segments.append(EvalTranscriptSegment(
                    id=str(seg.get("id", "")),
                    start_ms=int(seg.get("start_ms", 0)),
                    end_ms=int(seg.get("end_ms", 0)),
                    text=str(seg.get("text", "")),
                    is_visual_trigger=bool(seg.get("is_visual_trigger", False)),
                    trigger_type=seg.get("trigger_type"),
                ))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Note content — claims carry source_type so the frontend can split
    # into transcript / visual / screen / physician_edit groups.
    note_sections: list[dict] = []
    note_specialty = ""
    note_stage = 0
    note_completeness = 0.0
    note_version = 0
    if latest_note is not None:
        note_specialty = latest_note.specialty
        note_stage = latest_note.stage
        note_completeness = latest_note.completeness_score
        note_version = latest_note.version
        try:
            parsed = json.loads(latest_note.content)
            note_sections = parsed.get("sections", []) or []
        except (json.JSONDecodeError, TypeError):
            pass

    return EvalSessionDetailResponse(
        id=f"eval_{sid[:8]}",
        session_id=sid,
        clinician_name=clinician_name,
        specialty=s.specialty,
        transcript_masked=True,
        frames_masked=frames_masked,
        note_version=note_version,
        scored=score_row is not None,
        scores=_score_payload(score_row) if score_row else None,
        created_at=s.created_at.isoformat() if s.created_at else "",
        assigned_to=assignment.assignee_email if assignment else None,
        assignment_completed_at=(
            assignment.completed_at.isoformat()
            if assignment and assignment.completed_at
            else None
        ),
        transcript_provider=transcript_provider,
        transcript_segments=transcript_segments,
        note_specialty=note_specialty,
        note_stage=note_stage,
        note_completeness_score=note_completeness,
        note_sections=note_sections,
    )


@router.post("/eval/sessions/{session_id}/score", response_model=EvalSessionResponse)
async def submit_eval_score(
    session_id: uuid.UUID,
    body: EvalScoreRequest,
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Submit (or re-submit) quality scores for a session. EVAL_TEAM or ADMIN."""
    # FastAPI validates the uuid.UUID path param → a malformed id returns a
    # CORS-bearing 422 before we get here (matches sessions/media/users).
    sid_uuid = session_id

    session = await get_session_or_404(db, sid_uuid)

    overall = round(
        (body.transcript_accuracy + body.citation_correctness + body.descriptive_mode_compliance) / 3,
        1,
    )

    # OV-1 (#74): stamp provider attribution from the scored note so
    # quality scores join to providers without chasing the chain later.
    latest_note = await note_repo.get_latest_version(db, sid_uuid)
    provider_used = latest_note.provider_used if latest_note else None

    row = await eval_repo.upsert_score(
        db,
        session_id=sid_uuid,
        transcript_accuracy=body.transcript_accuracy,
        citation_correctness=body.citation_correctness,
        descriptive_mode_compliance=body.descriptive_mode_compliance,
        overall=overall,
        notes=body.notes,
        scored_by=user.email,
        descriptive_mode_pass=body.descriptive_mode_pass,
        soap_section_scores=body.soap_section_scores,
        hallucination_count=body.hallucination_count,
        discrepancies=body.discrepancies,
        provider_used=provider_used,
    )

    await write_audit(
        session_id,
        AuditEventType.EVAL_SCORE_SUBMITTED,
        overall_score=overall,
        scored_by=user.email,
    )

    # EVAL-3: if there's an open assignment, mark it complete. The audit
    # event traces "who closed which assignment by scoring".
    completed = await eval_repo.mark_assignment_complete(db, sid_uuid)
    if completed is not None and completed.completed_at is not None:
        await write_audit(
            session_id,
            AuditEventType.EVAL_ASSIGNMENT_COMPLETED,
            assignee_email=completed.assignee_email,
            completed_via_score=True,
        )

    names = await resolve_clinician_names(db, [session.clinician_id])
    clinician_name = names[str(session.clinician_id)]

    return EvalSessionResponse(
        id=f"eval_{session_id[:8]}",
        session_id=session_id,
        clinician_name=clinician_name,
        specialty=session.specialty,
        transcript_masked=True,
        frames_masked=True,
        note_version=0,
        scored=True,
        scores=_score_payload(row),
        created_at=session.created_at.isoformat() if session.created_at else "",
        assigned_to=completed.assignee_email if completed else None,
        assignment_completed_at=(
            completed.completed_at.isoformat()
            if completed and completed.completed_at
            else None
        ),
    )


# ── EVAL-3: assignment endpoints ───────────────────────────────────────────


@router.post(
    "/eval/sessions/{session_id}/assign",
    response_model=EvalSessionResponse,
)
async def assign_eval_session(
    session_id: uuid.UUID,
    body: EvalAssignmentRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """ADMIN-only: assign this session to a specific eval-team user.

    Idempotent — re-assigning the same session to a different user
    overwrites the existing assignment row. The new assignee sees the
    session in their queue immediately; the previous assignee no longer
    does.
    """
    # FastAPI validates the uuid.UUID path param → a malformed id returns a
    # CORS-bearing 422 before we get here (matches sessions/media/users).
    sid_uuid = session_id

    session = await get_session_or_404(db, sid_uuid)

    assignee = await users_repo.get_by_email(db, body.assignee_email)
    if assignee is None:
        raise HTTPException(
            status_code=400,
            detail=f"No user with email '{body.assignee_email}'",
        )
    if assignee.role not in (UserRole.EVAL_TEAM, UserRole.ADMIN):
        raise HTTPException(
            status_code=400,
            detail="Assignee must have role EVAL_TEAM or ADMIN",
        )

    assignment = await eval_repo.upsert_assignment(
        db,
        session_id=sid_uuid,
        assignee_user_id=assignee.id,
        assignee_email=assignee.email,
        assigned_by=user.user_id,
        assigned_by_email=user.email,
    )

    await write_audit(
        session_id,
        AuditEventType.EVAL_ASSIGNMENT_CREATED,
        assignee_email=assignee.email,
        assigned_by=user.email,
    )

    names = await resolve_clinician_names(db, [session.clinician_id])
    clinician_name = names[str(session.clinician_id)]
    score_row = await eval_repo.get_score(db, sid_uuid)
    latest_note = await note_repo.get_latest_version(db, sid_uuid)
    note_version = latest_note.version if latest_note else 0

    return EvalSessionResponse(
        id=f"eval_{session_id[:8]}",
        session_id=session_id,
        clinician_name=clinician_name,
        specialty=session.specialty,
        transcript_masked=True,
        frames_masked=True,
        note_version=note_version,
        scored=score_row is not None,
        scores=_score_payload(score_row) if score_row else None,
        created_at=session.created_at.isoformat() if session.created_at else "",
        assigned_to=assignment.assignee_email,
        assignment_completed_at=None,
    )


@router.delete(
    "/eval/sessions/{session_id}/assign",
    response_model=EvalSessionResponse,
)
async def unassign_eval_session(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """ADMIN-only: remove any assignment for this session."""
    # FastAPI validates the uuid.UUID path param → a malformed id returns a
    # CORS-bearing 422 before we get here (matches sessions/media/users).
    sid_uuid = session_id

    session = await get_session_or_404(db, sid_uuid)
    prior = await eval_repo.get_assignment(db, sid_uuid)
    await eval_repo.delete_assignment(db, sid_uuid)

    if prior is not None:
        await write_audit(
            session_id,
            AuditEventType.EVAL_ASSIGNMENT_REMOVED,
            assignee_email=prior.assignee_email,
            removed_by=user.email,
        )

    names = await resolve_clinician_names(db, [session.clinician_id])
    clinician_name = names[str(session.clinician_id)]
    score_row = await eval_repo.get_score(db, sid_uuid)
    latest_note = await note_repo.get_latest_version(db, sid_uuid)
    note_version = latest_note.version if latest_note else 0

    return EvalSessionResponse(
        id=f"eval_{session_id[:8]}",
        session_id=session_id,
        clinician_name=clinician_name,
        specialty=session.specialty,
        transcript_masked=True,
        frames_masked=True,
        note_version=note_version,
        scored=score_row is not None,
        scores=_score_payload(score_row) if score_row else None,
        created_at=session.created_at.isoformat() if session.created_at else "",
        assigned_to=None,
        assignment_completed_at=None,
    )


@router.get("/eval/assignees", response_model=list[EvalAssigneeResponse])
async def list_eval_assignees(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """ADMIN-only: list users eligible to receive eval assignments
    (role EVAL_TEAM or ADMIN). Surfaces the assignee picker on the
    detail page."""
    from app.core.models import UserModel

    stmt = (
        select(UserModel)
        .where(UserModel.role.in_([UserRole.EVAL_TEAM, UserRole.ADMIN]))
        .where(UserModel.is_active.is_(True))
        .order_by(UserModel.full_name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        EvalAssigneeResponse(
            user_id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
        )
        for u in rows
    ]
