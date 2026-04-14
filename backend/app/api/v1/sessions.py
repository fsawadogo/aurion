"""Session API routes — create, consent, start, pause, resume, stop.

No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import SessionState, UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user, require_role
from app.modules.session.service import (
    ConsentRequiredError,
    InvalidTransitionError,
    confirm_consent,
    create_session,
    get_audit_event_for_state,
    get_session,
    list_sessions,
    transition_session,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Request/Response Schemas ──────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    specialty: str
    provider_overrides: Optional[dict] = None


class SessionResponse(BaseModel):
    id: uuid.UUID
    clinician_id: uuid.UUID
    specialty: str
    state: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_session_route(
    body: CreateSessionRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await create_session(
        db=db,
        clinician_id=user.user_id,
        specialty=body.specialty,
        provider_overrides=body.provider_overrides,
    )
    audit = get_audit_log_service()
    await audit.write_event(
        session_id=session.id,
        event_type="session_created",
        clinician_id=str(user.user_id),
        specialty=body.specialty,
    )
    return _to_response(session)


@router.post("/{session_id}/consent", response_model=SessionResponse)
async def confirm_consent_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_or_404(db, session_id)
    await confirm_consent(db, session)
    audit = get_audit_log_service()
    await audit.write_event(
        session_id=session.id,
        event_type="consent_confirmed",
    )
    return _to_response(session)


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_recording_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_or_404(db, session_id)
    return await _do_transition(db, session, SessionState.RECORDING)


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def pause_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_or_404(db, session_id)
    return await _do_transition(db, session, SessionState.PAUSED)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_or_404(db, session_id)
    return await _do_transition(db, session, SessionState.RECORDING)


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_recording_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_or_404(db, session_id)
    return await _do_transition(db, session, SessionState.PROCESSING_STAGE1)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_or_404(db, session_id)
    return _to_response(session)


@router.get("", response_model=list[SessionResponse])
async def list_sessions_route(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await list_sessions(db, clinician_id=user.user_id)
    return [_to_response(s) for s in sessions]


# ── Helpers ───────────────────────────────────────────────────────────────

async def _get_or_404(db: AsyncSession, session_id: uuid.UUID):
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _do_transition(db, session, target_state: SessionState) -> SessionResponse:
    try:
        session = await transition_session(db, session, target_state)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConsentRequiredError as e:
        raise HTTPException(status_code=403, detail=str(e))

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=session.id,
        event_type=get_audit_event_for_state(target_state),
    )
    return _to_response(session)


def _to_response(session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        clinician_id=session.clinician_id,
        specialty=session.specialty,
        state=session.state.value if isinstance(session.state, SessionState) else session.state,
        created_at=session.created_at.isoformat() if session.created_at else "",
        updated_at=session.updated_at.isoformat() if session.updated_at else "",
    )
