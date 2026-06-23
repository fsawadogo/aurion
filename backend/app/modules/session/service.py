"""Session state machine — 10 states, every transition audited.

The record button is hard-blocked in IDLE and CONSENT_PENDING.
Invalid transitions are rejected. No session ends without an audit trail.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.models import (
    EvalAssignmentModel,
    EvalScoreModel,
    MeasurementCitationModel,
    NoteVersionModel,
    PhysicianProfileModel,
    PilotMetricsModel,
    SessionModel,
    Stage2JobModel,
    TranscriptModel,
)
from app.core.types import SessionState

logger = logging.getLogger("aurion.session")

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
        SessionState.STAGE1_FAILED,
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
    # STAGE1_FAILED is terminal for the same reason — the note-generation
    # provider call failed and there's no automatic re-run path; recovery is
    # the physician discarding the session and re-recording. Distinct from
    # NO_AUDIO so compliance dashboards can tell an empty-transcript skip from
    # a provider failure.
    SessionState.STAGE1_FAILED: [],  # terminal
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
    SessionState.STAGE1_FAILED: AuditEventType.STAGE1_FAILED,
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


async def resolve_context_template_key(
    db: AsyncSession,
    clinician_id: uuid.UUID,
    consultation_type: Optional[str],
    context_id: Optional[str],
) -> tuple[Optional[str], Optional[uuid.UUID], bool]:
    """Resolve the Stage-1 template SNAPSHOT for a chosen context (#314 / #318).

    Given the calling clinician + the visit type (``consultation_type``)
    + the chosen ``context_id``, look up the clinician's
    ``contexts_per_visit_type`` map (B1, #313) and resolve the template
    in this order:

      1. ``template_key`` — a built-in specialty template pinned to the
         context. Used when present AND still an available built-in. A
         context binds EITHER a ``template_key`` OR a ``template_ref``
         (mutual exclusion is enforced at PUT time, #318); the built-in
         pin is checked first so the common path never touches the
         ``custom_templates`` table.
      2. ``template_ref`` — phase 2 custom template (#318 / B3). The UUID
         of a ``custom_templates`` row. Re-resolved + ownership-checked
         HERE (defensively, even though PUT validated it) because the row
         could have been deleted between profile save and session create.
         An owned, existing ref snapshots its ``custom_template_id``.
      3. fall through to the session ``specialty`` default — represented
         as ``(None, None)`` so Stage 1 calls ``get_template(specialty)``
         exactly as it did pre-#314 (byte-for-byte back-compat).

    A pinned ``template_key`` that is no longer an available built-in
    (stale / renamed / removed from disk) OR a ``template_ref`` that no
    longer resolves to an owned existing custom template (deleted /
    unowned / malformed) is COERCED to the specialty default
    (``(None, None)``) and flagged so the caller can write a count-only
    audit note. Every "can't resolve" path — no ``context_id``, no
    ``consultation_type``, no profile, the visit type absent from the
    map, no matching context id, or a context that pinned nothing —
    degrades silently to ``(None, None, False)``. This function never
    raises.

    Returns ``(template_key, custom_template_id, coerced_stale)``:
      * ``template_key`` — a validated built-in key to snapshot, or
        ``None``.
      * ``custom_template_id`` — the owned custom-template UUID to
        snapshot, or ``None``. At most one of ``template_key`` /
        ``custom_template_id`` is non-None.
      * ``coerced_stale`` — ``True`` only when a non-null pin (built-in
        key or custom ref) was dropped because it no longer resolves.
    """
    if not context_id or not consultation_type:
        return None, None, False

    result = await db.execute(
        select(PhysicianProfileModel).where(
            PhysicianProfileModel.clinician_id == clinician_id
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return None, None, False

    try:
        contexts_map = json.loads(
            getattr(profile, "contexts_per_visit_type", None) or "{}"
        )
    except (TypeError, ValueError):
        return None, None, False
    if not isinstance(contexts_map, dict):
        return None, None, False

    contexts = contexts_map.get(consultation_type)
    if not isinstance(contexts, list):
        return None, None, False

    match: Optional[dict] = None
    for ctx in contexts:
        if isinstance(ctx, dict) and ctx.get("id") == context_id:
            match = ctx
            break
    if match is None:
        return None, None, False

    # Resolution order: template_key (built-in) → template_ref (custom)
    # → specialty default. Built-in wins when both are present (defensive
    # — mutual exclusion at PUT time means this won't normally happen).
    template_key = match.get("template_key")
    if template_key and isinstance(template_key, str):
        # Lazy import: the route + transcription paths import both this
        # module and note_gen, so we defer the cross-module import to call
        # time to stay clear of any import-order coupling.
        from app.modules.note_gen.service import list_available_templates

        if template_key not in list_available_templates():
            # Stale / renamed pin — coerce to the specialty default and
            # flag for a count-only audit note. Never errors the create.
            logger.info(
                "Context template_key for clinician=%s coerced to specialty "
                "default (no longer an available template)",
                clinician_id,
            )
            return None, None, True
        return template_key, None, False

    # No built-in pin — try a custom template_ref (#318 / B3).
    template_ref = match.get("template_ref")
    if template_ref and isinstance(template_ref, str):
        return await _resolve_custom_template_ref(
            db, clinician_id, template_ref
        )

    # Context pinned nothing → specialty default.
    return None, None, False


async def _resolve_custom_template_ref(
    db: AsyncSession,
    clinician_id: uuid.UUID,
    template_ref: str,
) -> tuple[Optional[str], Optional[uuid.UUID], bool]:
    """Re-resolve a custom ``template_ref`` at session-create time (#318).

    Returns ``(None, custom_template_id, False)`` when the ref parses as a
    UUID AND points at a ``custom_templates`` row owned by
    ``clinician_id``. Any failure — malformed UUID, deleted row, or a row
    owned by someone else (the owner-scoped lookup collapses both into a
    ``None`` result) — degrades to the specialty default
    ``(None, None, True)`` with the coercion flag set so the caller emits
    a count-only audit note. Never raises.
    """
    try:
        ref_uuid = uuid.UUID(template_ref)
    except (ValueError, TypeError, AttributeError):
        logger.info(
            "Context template_ref for clinician=%s coerced to specialty "
            "default (malformed reference)",
            clinician_id,
        )
        return None, None, True

    # Lazy import — same import-order rationale as the note_gen import
    # above; the custom-templates service owns the ownership-scoped read.
    from app.modules.custom_templates.service import get_owned

    owned = await get_owned(ref_uuid, clinician_id, db)
    if owned is None:
        logger.info(
            "Context template_ref for clinician=%s coerced to specialty "
            "default (no longer an owned custom template)",
            clinician_id,
        )
        return None, None, True

    return None, owned.id, False


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
    context_id: Optional[str] = None,
    template_key: Optional[str] = None,
    custom_template_id: Optional[uuid.UUID] = None,
) -> SessionModel:
    """Create a new session in CONSENT_PENDING state.

    `provider_overrides` is the validated dict from the route (P1-7
    closed-key Pydantic schema upstream). Persisted as JSON so the
    response path can round-trip it; pre-P1-7 rows used `str(dict)`
    which is not valid JSON and decoded as `None` on read — those rows
    keep working, they just don't expose overrides on subsequent GETs.

    `context_id`, `template_key`, and `custom_template_id` carry the
    resolved Visit Type → Context → Template selection (#314 / #318). All
    are computed by ``resolve_context_template_key`` upstream and
    persisted verbatim. `template_key=None` AND `custom_template_id=None`
    means "use the session specialty default" at Stage 1, exactly as
    before this feature existed. At most one of `template_key` /
    `custom_template_id` is non-None — a context binds either a built-in
    template or a custom one.
    """
    participants_json = json.dumps(participants) if participants else None
    # JSON encode so `_to_response` can round-trip via json.loads. The
    # previous str(...) call produced Python repr (single quotes, enum
    # references) which is not parseable; the field was effectively
    # write-only on the wire.
    overrides_json = json.dumps(provider_overrides) if provider_overrides else None

    if capture_mode not in VALID_CAPTURE_MODES:
        capture_mode = "multimodal"

    session = SessionModel(
        clinician_id=clinician_id,
        specialty=specialty,
        consultation_type=consultation_type,
        encounter_context=encounter_context,
        context_id=context_id,
        template_key=template_key,
        custom_template_id=custom_template_id,
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
    MeasurementCitationModel,  # #63 — derived PHI, erased with the session
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
