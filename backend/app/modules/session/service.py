"""Session state machine — 10 states, every transition audited.

The record button is hard-blocked in IDLE and CONSENT_PENDING.
Invalid transitions are rejected. No session ends without an audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import SessionModel
from app.core.types import SessionState

# ── Valid Transitions ──────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[SessionState, list[SessionState]] = {
    SessionState.IDLE: [SessionState.CONSENT_PENDING],
    SessionState.CONSENT_PENDING: [SessionState.RECORDING],
    SessionState.RECORDING: [SessionState.PAUSED, SessionState.PROCESSING_STAGE1],
    SessionState.PAUSED: [SessionState.RECORDING, SessionState.PROCESSING_STAGE1],
    SessionState.PROCESSING_STAGE1: [SessionState.AWAITING_REVIEW],
    SessionState.AWAITING_REVIEW: [SessionState.PROCESSING_STAGE2],
    SessionState.PROCESSING_STAGE2: [SessionState.REVIEW_COMPLETE],
    SessionState.REVIEW_COMPLETE: [SessionState.EXPORTED],
    SessionState.EXPORTED: [SessionState.PURGED],
    SessionState.PURGED: [],  # terminal
}

# ── Audit Event Mapping ──────────��────────────────────────────────────────

STATE_AUDIT_EVENTS: dict[SessionState, str] = {
    SessionState.IDLE: "session_created",
    SessionState.CONSENT_PENDING: "session_created",
    SessionState.RECORDING: "recording_started",
    SessionState.PAUSED: "session_paused",
    SessionState.PROCESSING_STAGE1: "stage1_started",
    SessionState.AWAITING_REVIEW: "stage1_delivered",
    SessionState.PROCESSING_STAGE2: "stage2_started",
    SessionState.REVIEW_COMPLETE: "full_note_delivered",
    SessionState.EXPORTED: "note_exported",
    SessionState.PURGED: "session_purged",
}


class InvalidTransitionError(Exception):
    def __init__(self, current: SessionState, target: SessionState):
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value} → {target.value}")


class ConsentRequiredError(Exception):
    def __init__(self):
        super().__init__("Patient consent must be confirmed before recording can begin.")


# ── Service Functions ──────────────────────────────────────────────────────

async def create_session(
    db: AsyncSession,
    clinician_id: uuid.UUID,
    specialty: str,
    consultation_type: Optional[str] = None,
    encounter_context: Optional[str] = None,
    output_language: str = "en",
    encounter_type: str = "doctor_patient",
    participants: Optional[list[dict]] = None,
    provider_overrides: Optional[dict] = None,
) -> SessionModel:
    """Create a new session in CONSENT_PENDING state."""
    import json as _json
    participants_json = _json.dumps(participants) if participants else None

    session = SessionModel(
        clinician_id=clinician_id,
        specialty=specialty,
        consultation_type=consultation_type,
        encounter_context=encounter_context,
        output_language=output_language,
        encounter_type=encounter_type,
        participants_json=participants_json,
        state=SessionState.CONSENT_PENDING,
        provider_overrides=str(provider_overrides) if provider_overrides else None,
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Optional[SessionModel]:
    """Get a session by ID."""
    result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    return result.scalar_one_or_none()


async def transition_session(
    db: AsyncSession,
    session: SessionModel,
    target_state: SessionState,
) -> SessionModel:
    """Transition a session to a new state.

    Validates the transition is legal. Raises InvalidTransitionError
    if not. Returns the updated session.
    """
    current = session.state

    # Validate transition
    allowed = VALID_TRANSITIONS.get(current, [])
    if target_state not in allowed:
        raise InvalidTransitionError(current, target_state)

    # Consent hard block — cannot go to RECORDING without consent_confirmed
    if target_state == SessionState.RECORDING and current == SessionState.CONSENT_PENDING:
        if not session.consent_confirmed:
            raise ConsentRequiredError()

    session.state = target_state
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return session


def get_audit_event_for_state(state: SessionState) -> str:
    """Return the audit event type for a given state."""
    return STATE_AUDIT_EVENTS.get(state, f"state_changed_{state.value.lower()}")


async def confirm_consent(
    db: AsyncSession,
    session: SessionModel,
) -> SessionModel:
    """Explicit consent confirmation — sets consent_confirmed flag.

    Session stays in CONSENT_PENDING. The next call to transition_session
    to RECORDING is now valid (the flag is checked in the transition).
    """
    if session.state != SessionState.CONSENT_PENDING:
        raise InvalidTransitionError(session.state, SessionState.RECORDING)
    session.consent_confirmed = True
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return session


async def list_sessions(
    db: AsyncSession,
    clinician_id: Optional[uuid.UUID] = None,
) -> list[SessionModel]:
    """List sessions, optionally filtered by clinician."""
    stmt = select(SessionModel).order_by(SessionModel.created_at.desc())
    if clinician_id:
        stmt = stmt.where(SessionModel.clinician_id == clinician_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
