"""Eval team interface — list reviewable sessions and submit quality scores.

EVAL_TEAM or ADMIN. Scores are held in-memory today (``_EVAL_SCORES``);
migrates to a persistent ``eval_scores`` table when B-08 lands.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404, write_audit
from app.api.v1.admin._shared import (
    EvalScoreRequest,
    EvalSessionResponse,
    resolve_clinician_names,
    scan_audit_events,
)
from app.core.clock import utcnow
from app.core.database import get_db
from app.core.models import SessionModel
from app.core.types import SessionState, UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, require_role
from app.modules.note_gen import repository as note_repo

router = APIRouter(prefix="/admin", tags=["admin"])


# In-memory eval scores — migrates to PostgreSQL table in production (B-08).
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

    # Batch-load latest note versions + clinician names for all sessions
    # in single queries each to avoid N+1.
    notes_by_session = await note_repo.get_latest_versions_by_session(
        db, (s.id for s in sessions)
    )
    names_by_id = await resolve_clinician_names(
        db, (s.clinician_id for s in sessions)
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
        scores = _EVAL_SCORES.get(sid)
        latest_note = notes_by_session.get(s.id)
        note_version = latest_note.version if latest_note else 0

        eval_sessions.append(EvalSessionResponse(
            id=f"eval_{sid[:8]}",
            session_id=sid,
            clinician_name=clinician_name,
            specialty=s.specialty,
            transcript_masked=True,  # All transcripts are masked by policy
            frames_masked=sid in sessions_with_masking_confirmed,
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
    try:
        sid_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    session = await get_session_or_404(db, sid_uuid)

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
        "scored_at": utcnow().isoformat(),
    }

    _EVAL_SCORES[session_id] = scores

    await write_audit(
        session_id,
        "eval_score_submitted",
        overall_score=overall,
        scored_by=user.email,
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
        scores=scores,
        created_at=session.created_at.isoformat() if session.created_at else "",
    )
