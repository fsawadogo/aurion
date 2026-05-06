"""Notes API routes -- Stage 1 draft, approval, full note retrieval.

No business logic here -- routes call module service functions only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import SessionState
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.note_gen.service import (
    approve_note,
    edit_note,
    get_latest_note,
    get_note_by_stage,
    is_note_approved,
)
from app.modules.session.service import (
    InvalidTransitionError,
    get_session,
    transition_session,
)

router = APIRouter(prefix="/notes", tags=["notes"])


# ── Response Schemas ─────────────────────────────────────────────────────

class NoteClaimResponse(BaseModel):
    id: str
    text: str
    source_type: str
    source_id: str
    source_quote: str = ""


class NoteSectionResponse(BaseModel):
    id: str
    title: str = ""
    status: str = "not_captured"
    claims: list[NoteClaimResponse] = []


class NoteResponse(BaseModel):
    session_id: str
    stage: int
    version: int
    provider_used: str
    specialty: str
    completeness_score: float
    sections: list[NoteSectionResponse]


class NoteApprovalResponse(BaseModel):
    session_id: str
    stage: int
    version: int
    approved: bool
    message: str


class NoteEditRequest(BaseModel):
    """Request body for physician note edits.

    edits: dict mapping section_id to new claim text.
    Example: {"physical_exam": "Updated claim text...", "assessment": "..."}
    """
    edits: dict[str, str]


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/{session_id}/stage1", response_model=NoteResponse)
async def get_stage1_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the Stage 1 draft note for a session.

    The session must be in AWAITING_REVIEW or later state for the
    Stage 1 note to be available.
    """
    session = await _get_session_or_404(db, session_id)

    valid_states = {
        SessionState.AWAITING_REVIEW,
        SessionState.PROCESSING_STAGE2,
        SessionState.REVIEW_COMPLETE,
        SessionState.EXPORTED,
    }
    if session.state not in valid_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Stage 1 note not yet available. "
                f"Session is in {session.state.value}, must be in AWAITING_REVIEW or later."
            ),
        )

    note = await get_note_by_stage(str(session_id), stage=1, db=db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stage 1 note not found for this session.",
        )

    return _to_note_response(note)


@router.post("/{session_id}/approve-stage1", response_model=NoteApprovalResponse)
async def approve_stage1_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve the Stage 1 draft and trigger Stage 2 processing.

    Transitions the session from AWAITING_REVIEW to PROCESSING_STAGE2.
    Writes audit log events for the approval and state transition.
    """
    session = await _get_session_or_404(db, session_id)

    if session.state != SessionState.AWAITING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot approve Stage 1: session is in {session.state.value}, "
                f"must be in AWAITING_REVIEW."
            ),
        )

    note = await get_note_by_stage(str(session_id), stage=1, db=db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Stage 1 note found to approve.",
        )

    try:
        approved_note = await approve_note(str(session_id), db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    try:
        await transition_session(db, session, SessionState.PROCESSING_STAGE2)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(session_id),
        event_type="stage1_approved",
        version=approved_note.version,
        provider_used=approved_note.provider_used,
        completeness_score=approved_note.completeness_score,
    )
    await audit.write_event(
        session_id=str(session_id),
        event_type="stage2_started",
    )

    # Auto-fire Stage 2 vision enrichment. Done inline (not background) so the
    # iOS client receives a deterministic state — by the time approve-stage1
    # returns, the Stage 2 note version exists. If vision fails we log it and
    # keep the session in PROCESSING_STAGE2 so iOS can fall back to the
    # Stage 1 note (which is still the latest version).
    from app.api.v1.vision import run_stage2_vision  # avoid circular import
    try:
        await run_stage2_vision(session_id, db)
    except Exception as exc:
        await audit.write_event(
            session_id=str(session_id),
            event_type="stage2_failed",
            reason=str(exc)[:200],
        )
        # Don't propagate — Stage 1 is approved and iOS can proceed with the
        # Stage 1 note. Vision is best-effort; failures shouldn't block sign-off.

    return NoteApprovalResponse(
        session_id=str(session_id),
        stage=1,
        version=approved_note.version,
        approved=True,
        message="Stage 1 approved. Stage 2 visual enrichment processing started.",
    )


@router.get("/{session_id}/full", response_model=NoteResponse)
async def get_full_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full note (latest version) for a session.

    Returns the most recent note version, which may include Stage 2
    visual enrichments if processing is complete.
    """
    await _get_session_or_404(db, session_id)

    note = await get_latest_note(str(session_id), db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No note found for this session.",
        )

    return _to_note_response(note)


@router.post("/{session_id}/approve", response_model=NoteApprovalResponse)
async def approve_final_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve the final note after Stage 2 visual enrichment.

    Transitions the session to REVIEW_COMPLETE. Writes audit log event.

    CONFLICTS must be resolved before approval -- no note with unresolved
    CONFLICTS can be approved.
    """
    session = await _get_session_or_404(db, session_id)

    allowed_states = {SessionState.PROCESSING_STAGE2, SessionState.REVIEW_COMPLETE}
    if session.state not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot approve final note: session is in {session.state.value}. "
                f"Must be in PROCESSING_STAGE2 or REVIEW_COMPLETE."
            ),
        )

    note = await get_latest_note(str(session_id), db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No note found to approve.",
        )

    _check_unresolved_conflicts(note)

    already_approved = await is_note_approved(str(session_id), db)
    if already_approved and session.state == SessionState.REVIEW_COMPLETE:
        return NoteApprovalResponse(
            session_id=str(session_id),
            stage=note.stage,
            version=note.version,
            approved=True,
            message="Note was already approved.",
        )

    try:
        approved_note = await approve_note(str(session_id), db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    if session.state == SessionState.PROCESSING_STAGE2:
        try:
            await transition_session(db, session, SessionState.REVIEW_COMPLETE)
        except InvalidTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(session_id),
        event_type="full_note_delivered",
        version=approved_note.version,
        provider_used=approved_note.provider_used,
        completeness_score=approved_note.completeness_score,
    )

    return NoteApprovalResponse(
        session_id=str(session_id),
        stage=approved_note.stage,
        version=approved_note.version,
        approved=True,
        message="Final note approved. Ready for export.",
    )


@router.patch("/{session_id}/edit", response_model=NoteResponse)
async def edit_note_endpoint(
    session_id: uuid.UUID,
    body: NoteEditRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply physician edits to the latest note version.

    Creates a new immutable version -- the original is preserved.
    Session must be in AWAITING_REVIEW or REVIEW_COMPLETE state.
    """
    session = await _get_session_or_404(db, session_id)

    allowed_states = {SessionState.AWAITING_REVIEW, SessionState.REVIEW_COMPLETE}
    if session.state not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot edit note: session is in {session.state.value}. "
                f"Must be in AWAITING_REVIEW or REVIEW_COMPLETE."
            ),
        )

    if not body.edits:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No edits provided.",
        )

    try:
        updated_note = await edit_note(str(session_id), body.edits, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(session_id),
        event_type="note_version_created",
        version=updated_note.version,
        sections_edited=list(body.edits.keys()),
    )

    return _to_note_response(updated_note)


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_session_or_404(db: AsyncSession, session_id: uuid.UUID):
    """Retrieve a session or raise 404."""
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    return session


def _check_unresolved_conflicts(note) -> None:
    """Raise 409 if the note has any unresolved CONFLICTS from vision."""
    for section in note.sections:
        for claim in section.claims:
            if claim.source_type == "visual" and claim.id.startswith("conflict_"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Unresolved conflict in section '{section.id}'. "
                        "All conflicts must be resolved before approval."
                    ),
                )


def _to_note_response(note) -> NoteResponse:
    """Convert a Note domain object to a NoteResponse."""
    return NoteResponse(
        session_id=note.session_id,
        stage=note.stage,
        version=note.version,
        provider_used=note.provider_used,
        specialty=note.specialty,
        completeness_score=note.completeness_score,
        sections=[
            NoteSectionResponse(
                id=s.id,
                title=s.title,
                status=s.status,
                claims=[
                    NoteClaimResponse(
                        id=c.id,
                        text=c.text,
                        source_type=c.source_type,
                        source_id=c.source_id,
                        source_quote=c.source_quote,
                    )
                    for c in s.claims
                ],
            )
            for s in note.sections
        ],
    )
