"""Eval team interface — list reviewable sessions and submit quality scores.

EVAL_TEAM or ADMIN. Scores persist in the ``eval_scores`` table (B-08).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404, write_audit
from app.api.v1.admin._shared import (
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
from app.modules.auth.service import CurrentUser, require_role
from app.modules.eval import repository as eval_repo
from app.modules.note_gen import repository as note_repo

import json

router = APIRouter(prefix="/admin", tags=["admin"])


def _score_payload(row: EvalScoreModel) -> dict:
    """Serialize an EvalScoreModel into the legacy response dict shape.

    The shape is preserved verbatim so the web portal (and any other
    client reading ``scores``) keeps working without a frontend change.
    """
    return {
        "transcript_accuracy": row.transcript_accuracy,
        "citation_correctness": row.citation_correctness,
        "descriptive_mode_compliance": row.descriptive_mode_compliance,
        "overall": row.overall,
        "notes": row.notes,
        "scored_by": row.scored_by,
        "scored_at": row.scored_at.isoformat() if row.scored_at else "",
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
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Batch-load notes, clinician names, and eval scores in single queries.
    notes_by_session = await note_repo.get_latest_versions_by_session(
        db, (s.id for s in sessions)
    )
    names_by_id = await resolve_clinician_names(
        db, (s.clinician_id for s in sessions)
    )
    scores_by_session = await eval_repo.get_scores_by_sessions(
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
        ))

    return eval_sessions


@router.get("/eval/sessions/{session_id}", response_model=EvalSessionDetailResponse)
async def get_eval_session_detail(
    session_id: str,
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
    try:
        sid_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

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
        transcript_provider=transcript_provider,
        transcript_segments=transcript_segments,
        note_specialty=note_specialty,
        note_stage=note_stage,
        note_completeness_score=note_completeness,
        note_sections=note_sections,
    )


@router.post("/eval/sessions/{session_id}/score", response_model=EvalSessionResponse)
async def submit_eval_score(
    session_id: str,
    body: EvalScoreRequest,
    user: CurrentUser = Depends(
        require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Submit (or re-submit) quality scores for a session. EVAL_TEAM or ADMIN."""
    try:
        sid_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    session = await get_session_or_404(db, sid_uuid)

    overall = round(
        (body.transcript_accuracy + body.citation_correctness + body.descriptive_mode_compliance) / 3,
        1,
    )

    row = await eval_repo.upsert_score(
        db,
        session_id=sid_uuid,
        transcript_accuracy=body.transcript_accuracy,
        citation_correctness=body.citation_correctness,
        descriptive_mode_compliance=body.descriptive_mode_compliance,
        overall=overall,
        notes=body.notes,
        scored_by=user.email,
    )

    await write_audit(
        session_id,
        AuditEventType.EVAL_SCORE_SUBMITTED,
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
        scores=_score_payload(row),
        created_at=session.created_at.isoformat() if session.created_at else "",
    )
