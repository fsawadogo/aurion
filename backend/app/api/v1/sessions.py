"""Session API routes — create, consent, start, pause, resume, stop.

No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import (
    get_owned_session_or_404,
    require_state,
    write_audit,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.kms_encryption import decrypt_str, encrypt_str
from app.core.types import SessionState
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.session.service import (
    ConsentRequiredError,
    InvalidTransitionError,
    confirm_consent,
    create_session,
    delete_session,
    get_audit_event_for_state,
    list_sessions,
    transition_session,
)

logger = logging.getLogger("aurion.api.sessions")

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Request/Response Schemas ──────────────────────────────────────────────

class SessionParticipantRequest(BaseModel):
    name: str
    role: str
    is_persistent: bool = False


class CreateSessionRequest(BaseModel):
    specialty: str
    consultation_type: Optional[str] = None
    encounter_context: Optional[str] = None
    output_language: str = "en"
    encounter_type: str = "doctor_patient"
    participants: Optional[list[SessionParticipantRequest]] = None
    provider_overrides: Optional[dict] = None
    capture_mode: str = "multimodal"


class SessionResponse(BaseModel):
    id: uuid.UUID
    clinician_id: uuid.UUID
    specialty: str
    state: str
    encounter_type: str = "doctor_patient"
    capture_mode: str = "multimodal"
    # Optional PHI identifier set by the clinician to link this session
    # back to their own patient roster (MRN hash, EMR encounter id, free
    # text — whatever the clinic uses). Decrypted server-side and only
    # populated for the owner of the row. Other CLINICIAN callers get a
    # 404 on the session entirely; admin/compliance get the row but with
    # this field omitted (we don't surface decrypted PHI cross-clinician).
    external_reference_id: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ExternalReferenceIdRequest(BaseModel):
    """Patch body for setting / clearing the patient identifier.

    Empty string or null clears the column; any other string is encrypted
    via KMS and stored as bytea. Format validation is intentionally
    permissive at the API boundary — different clinics use different
    schemes (MRN, encounter id, free text); the canonical validation
    happens in the EMR write-back integration (#57).
    """

    external_reference_id: Optional[str] = None


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
        consultation_type=body.consultation_type,
        encounter_context=body.encounter_context,
        output_language=body.output_language,
        encounter_type=body.encounter_type,
        participants=[p.model_dump() for p in body.participants] if body.participants else None,
        provider_overrides=body.provider_overrides,
        capture_mode=body.capture_mode,
    )
    await write_audit(
        session.id,
        AuditEventType.SESSION_CREATED,
        clinician_id=str(user.user_id),
        specialty=body.specialty,
    )
    return _to_response(session)


ConsentMethod = Literal["verbal", "paper_form", "digital_form"]


class ConfirmConsentRequest(BaseModel):
    consent_method: ConsentMethod


@router.post("/{session_id}/consent", response_model=SessionResponse)
async def confirm_consent_route(
    session_id: uuid.UUID,
    body: ConfirmConsentRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    await confirm_consent(db, session)
    await write_audit(
        session.id,
        AuditEventType.CONSENT_CONFIRMED,
        consent_method=body.consent_method,
    )
    return _to_response(session)


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_recording_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.RECORDING)


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def pause_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.PAUSED)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.RECORDING)


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_recording_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.PROCESSING_STAGE1)


class UpdateTemplateRequest(BaseModel):
    specialty: str


@router.patch("/{session_id}/template", response_model=SessionResponse)
async def update_session_template(
    session_id: uuid.UUID,
    body: UpdateTemplateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the session specialty/template after recording, before note generation.

    Only valid when the session is in PROCESSING_STAGE1 state (audio submitted
    but note not yet generated).
    """
    session = await get_owned_session_or_404(db, session_id, user)
    require_state(session, SessionState.PROCESSING_STAGE1)
    session.specialty = body.specialty
    await db.flush()

    await write_audit(session.id, AuditEventType.TEMPLATE_CHANGED, new_specialty=body.specialty)
    return _to_response(session)


@router.patch(
    "/{session_id}/identifier", response_model=SessionResponse
)
async def set_session_external_reference_id(
    session_id: uuid.UUID,
    body: ExternalReferenceIdRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the patient identifier (external_reference_id) on a session.

    The identifier is PHI: KMS-encrypted at rest, never logged in
    plaintext, never returned to non-owner callers. Empty string or
    null clears the column (and emits an audit event with
    `cleared=True` so the trail captures the deletion).

    Owner-only — non-owner CLINICIAN gets 404 from get_owned_session_or_404.
    """
    session = await get_owned_session_or_404(db, session_id, user)
    raw = (body.external_reference_id or "").strip()
    cleared = not raw
    if cleared:
        session.external_reference_id_encrypted = None
    else:
        session.external_reference_id_encrypted = encrypt_str(raw)
    await db.flush()

    # Audit row carries only the bool — never the identifier value
    # itself. The audit log is append-only; leaking PHI there would
    # be permanent.
    await write_audit(
        session.id,
        AuditEventType.EXTERNAL_REFERENCE_ID_SET,
        actor_id=str(user.user_id),
        cleared=cleared,
    )
    return _to_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return _to_response(session)


@router.get("", response_model=list[SessionResponse])
async def list_sessions_route(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await list_sessions(db, clinician_id=user.user_id)
    return [_to_response(s) for s in sessions]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a session and all of its data.

    Clinician-scoped self-service cleanup (e.g. clearing a session that
    got wedged in PROCESSING_STAGE1 after a failed Stage 1). The caller may
    only discard their own sessions — another clinician's session 404s so
    its existence isn't revealed. Removes the session plus its transcript /
    note-version / pilot-metric / stage-2 rows.

    The DynamoDB audit trail is append-only and is NOT erased: a
    ``session_discarded`` event is written instead, after the delete is
    durably committed, so the record of the deletion survives.
    """
    # get_owned_session_or_404 already enforces ownership (clinician must
    # match; 404 leaks nothing about other clinicians' sessions).
    session = await get_owned_session_or_404(db, session_id, user)
    prior_state = (
        session.state.value
        if isinstance(session.state, SessionState)
        else str(session.state)
    )
    await delete_session(db, session)
    await db.commit()
    await write_audit(
        session_id, AuditEventType.SESSION_DISCARDED, prior_state=prior_state
    )


# ── Helpers ───────────────────────────────────────────────────────────────

async def _do_transition(db, session, target_state: SessionState) -> SessionResponse:
    try:
        session = await transition_session(db, session, target_state)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConsentRequiredError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await write_audit(session.id, get_audit_event_for_state(target_state))
    return _to_response(session)


def _to_response(session) -> SessionResponse:
    """Map a SessionModel row to its API response.

    Every caller in this module is reached only after ownership has been
    confirmed by `get_owned_session_or_404` (or filters to
    `clinician_id == user.user_id` for the list path), so it's safe to
    decrypt the identifier here unconditionally — there is no public
    surface where _to_response runs against another clinician's row.
    """
    external_id: Optional[str] = None
    if getattr(session, "external_reference_id_encrypted", None):
        try:
            external_id = decrypt_str(session.external_reference_id_encrypted)
        except Exception as exc:
            # Never crash the response on a decryption failure; log +
            # omit. If the KMS key rotated and old ciphertexts can't be
            # decrypted that's a CMK rotation incident, not a 500.
            logger.warning(
                "Failed to decrypt external_reference_id for session=%s: %s",
                session.id, exc,
            )
    return SessionResponse(
        id=session.id,
        clinician_id=session.clinician_id,
        specialty=session.specialty,
        state=session.state.value if isinstance(session.state, SessionState) else session.state,
        encounter_type=session.encounter_type or "doctor_patient",
        capture_mode=getattr(session, "capture_mode", None) or "multimodal",
        external_reference_id=external_id,
        created_at=session.created_at.isoformat() if session.created_at else "",
        updated_at=session.updated_at.isoformat() if session.updated_at else "",
    )
