"""Session state machine — 10 states, every transition audited.

The record button is hard-blocked in IDLE and CONSENT_PENDING.
Invalid transitions are rejected. No session ends without an audit trail.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.models import (
    EvalAssignmentModel,
    EvalScoreModel,
    NoteVersionModel,
    PilotMetricsModel,
    SessionModel,
    Stage2JobModel,
    TranscriptModel,
)
from app.core.types import SessionState

# ── Valid Transitions ──────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[SessionState, list[SessionState]] = {
    SessionState.IDLE: [SessionState.CONSENT_PENDING],
    SessionState.CONSENT_PENDING: [SessionState.RECORDING],
    SessionState.RECORDING: [SessionState.PAUSED, SessionState.PROCESSING_STAGE1],
    SessionState.PAUSED: [SessionState.RECORDING, SessionState.PROCESSING_STAGE1],
    # PROCESSING_STAGE1 can also drop to STAGE1_FAILED_NO_AUDIO when the
    # transcript is empty / minimal — see ``generate_stage1_note``. The
    # provider is never called in that branch, so the only legal next
    # step is AWAITING_REVIEW (happy path) or the failure terminal.
    SessionState.PROCESSING_STAGE1: [
        SessionState.AWAITING_REVIEW,
        SessionState.STAGE1_FAILED_NO_AUDIO,
    ],
    SessionState.AWAITING_REVIEW: [SessionState.PROCESSING_STAGE2],
    SessionState.PROCESSING_STAGE2: [SessionState.REVIEW_COMPLETE],
    SessionState.REVIEW_COMPLETE: [SessionState.EXPORTED],
    SessionState.EXPORTED: [SessionState.PURGED],
    SessionState.PURGED: [],  # terminal
    # STAGE1_FAILED_NO_AUDIO is terminal — the only recovery is the
    # physician discarding the session (DELETE /sessions/{id}) and
    # starting a fresh one. No forward transition because there's no
    # audio to retry against.
    SessionState.STAGE1_FAILED_NO_AUDIO: [],  # terminal
}

# ── Audit Event Mapping ──────────��────────────────────────────────────────

STATE_AUDIT_EVENTS: dict[SessionState, AuditEventType] = {
    SessionState.IDLE: AuditEventType.SESSION_CREATED,
    SessionState.CONSENT_PENDING: AuditEventType.SESSION_CREATED,
    SessionState.RECORDING: AuditEventType.RECORDING_STARTED,
    SessionState.PAUSED: AuditEventType.SESSION_PAUSED,
    SessionState.PROCESSING_STAGE1: AuditEventType.STAGE1_STARTED,
    SessionState.AWAITING_REVIEW: AuditEventType.STAGE1_DELIVERED,
    SessionState.PROCESSING_STAGE2: AuditEventType.STAGE2_STARTED,
    SessionState.REVIEW_COMPLETE: AuditEventType.FULL_NOTE_DELIVERED,
    SessionState.EXPORTED: AuditEventType.NOTE_EXPORTED,
    SessionState.PURGED: AuditEventType.SESSION_PURGED,
    # The transcript-empty guard fires a STAGE1_SKIPPED_* event with the
    # concrete reason BEFORE this state transition; mapping the state
    # transition itself to STAGE1_FAILED keeps the state-machine audit
    # uniform and lets compliance dashboards continue to roll up "Stage 1
    # failed" without learning a new event name.
    SessionState.STAGE1_FAILED_NO_AUDIO: AuditEventType.STAGE1_FAILED,
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

VALID_CAPTURE_MODES = {"multimodal", "audio_only", "smart_dictation"}


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
    capture_mode: str = "multimodal",
) -> SessionModel:
    """Create a new session in CONSENT_PENDING state.

    `provider_overrides` is the validated dict from the route (P1-7
    closed-key Pydantic schema upstream). Persisted as JSON so the
    response path can round-trip it; pre-P1-7 rows used `str(dict)`
    which is not valid JSON and decoded as `None` on read — those rows
    keep working, they just don't expose overrides on subsequent GETs.
    """
    import json as _json
    participants_json = _json.dumps(participants) if participants else None
    # JSON encode so `_to_response` can round-trip via json.loads. The
    # previous str(...) call produced Python repr (single quotes, enum
    # references) which is not parseable; the field was effectively
    # write-only on the wire.
    overrides_json = _json.dumps(provider_overrides) if provider_overrides else None

    if capture_mode not in VALID_CAPTURE_MODES:
        capture_mode = "multimodal"

    session = SessionModel(
        clinician_id=clinician_id,
        specialty=specialty,
        consultation_type=consultation_type,
        encounter_context=encounter_context,
        output_language=output_language,
        encounter_type=encounter_type,
        participants_json=participants_json,
        capture_mode=capture_mode,
        state=SessionState.CONSENT_PENDING,
        provider_overrides=overrides_json,
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
    session.updated_at = utcnow()
    await db.flush()
    return session


def get_audit_event_for_state(state: SessionState) -> AuditEventType | str:
    """Return the audit event type for a given state.

    Returns an ``AuditEventType`` member for known states; falls back to
    a raw ``str`` for unknown ones (a SessionState added without
    updating ``STATE_AUDIT_EVENTS``). The fallback is a development
    guard — production should never hit it.
    """
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
    session.updated_at = utcnow()
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


# Tables keyed by ``session_id`` that must be cleared when a session is
# discarded. There are no DB-level FK cascades from these to ``sessions``
# (the columns are plain UUIDs), so deleting the session row alone would
# orphan them — delete them explicitly first.
_SESSION_CHILD_MODELS = (
    TranscriptModel,
    NoteVersionModel,
    PilotMetricsModel,
    Stage2JobModel,
    EvalScoreModel,
    EvalAssignmentModel,
)


async def delete_session(
    db: AsyncSession, session: SessionModel
) -> dict[str, int]:
    """Hard-delete a session and every row that references it.

    Runs as one transaction (the caller commits): child rows first, then
    the session itself. Returns per-table deleted-row counts for auditing.
    The DynamoDB audit trail is append-only and is intentionally NOT
    touched — the deletion is recorded by the caller writing a
    ``SESSION_DISCARDED`` event, not by erasing history.
    """
    counts: dict[str, int] = {}
    for model in _SESSION_CHILD_MODELS:
        result = await db.execute(
            delete(model).where(model.session_id == session.id)
        )
        counts[model.__tablename__] = result.rowcount or 0
    result = await db.execute(
        delete(SessionModel).where(SessionModel.id == session.id)
    )
    counts["sessions"] = result.rowcount or 0
    await db.flush()
    return counts
