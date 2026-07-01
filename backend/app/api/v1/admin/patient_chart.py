"""Cross-clinician Patient Chart — elevated-role, flag-dark (#604).

The aggregated "every encounter for this patient, across all staff" view
plus a supervisory note-validate action. Both surfaces are:

  * gated to CLINICAL_ADMIN + ADMIN (``require_role``), and
  * gated behind the ``cross_clinician_chart_enabled`` feature flag —
    every route 404s while it is OFF, so no cross-clinician PHI is
    reachable until compliance flips it (ships dark, same posture as
    ``video_import_enabled`` / ``grounded_synthesis_enabled``).

Regular CLINICIANs keep their owner-scoped ``/me/patients/{id}/sessions``
view (unchanged) — this module is a separate, more-privileged surface and
deliberately does NOT route through ``get_owned_session_or_404`` / the
``_OWNER_BYPASS_ROLES`` set (widening that would silently broaden every
existing ``/sessions``/``/notes`` route). The compensating control for
returning other clinicians' sessions is the role gate ∧ the flag, not
ownership.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404, write_audit
from app.api.v1.admin._shared import resolve_clinician_names
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.identifier_hash import hash_identifier
from app.core.models import SessionModel
from app.core.types import SessionState, UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_config
from app.modules.note_gen import repository as note_repo
from app.modules.note_gen.service import UnresolvedConflictError, approve_note
from app.modules.session.service import (
    InvalidTransitionError,
    transition_session,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Roles that may see the cross-clinician chart + validate any note. Kept
# separate from the eval-dashboard gate (EVAL_TEAM + ADMIN) on purpose —
# this surface is supervisory, not evaluation.
_CHART_ROLES = (UserRole.CLINICAL_ADMIN, UserRole.ADMIN)


def _require_chart_enabled() -> None:
    """404 unless the Patient Chart feature flag is ON.

    Raising 404 (not 403) keeps the whole surface invisible while dark —
    an off feature should look like it doesn't exist, matching the
    video-import master gate.
    """
    if not get_config().feature_flags.cross_clinician_chart_enabled:
        raise HTTPException(status_code=404, detail="Not found")


class PatientEncounter(BaseModel):
    """One encounter row in the cross-clinician chart.

    Slim + PHI-conscious: carries the clinician attribution and note
    status the chart needs to render, never claim text or the patient
    identifier (which stays hashed for the lookup).
    """

    session_id: str
    clinician_id: str
    clinician_name: str
    specialty: str
    state: str
    created_at: str
    note_version: int = 0
    note_stage: int = 0
    is_approved: bool = False


@router.get(
    "/patients/{identifier}/encounters",
    response_model=list[PatientEncounter],
)
async def list_patient_encounters(
    identifier: str,
    _user: CurrentUser = Depends(require_role(*_CHART_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[PatientEncounter]:
    """Every encounter tagged with this patient identifier, ACROSS all
    clinicians. CLINICAL_ADMIN / ADMIN only, and only while the
    ``cross_clinician_chart_enabled`` flag is ON.

    The cross-clinician counterpart to ``/me/patients/{id}/sessions``: it
    drops the ``clinician_id`` owner filter and keeps only the
    deterministic-HMAC identifier match (``hash_identifier`` →
    ``ix_sessions_external_reference_id_hash``). Clinician names + latest
    note version/approval are batch-resolved to avoid N+1.

    Empty/blank identifier → 422 (mirrors the owner endpoint).
    """
    _require_chart_enabled()

    target = identifier.strip()
    if not target:
        raise HTTPException(
            status_code=422, detail="identifier must be non-empty"
        )

    target_hash = hash_identifier(target)
    stmt = (
        select(SessionModel)
        .where(SessionModel.external_reference_id_hash == target_hash)
        .order_by(SessionModel.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    if not rows:
        return []

    notes_by_session = await note_repo.get_latest_versions_by_session(
        db, (r.id for r in rows)
    )
    names_by_id = await resolve_clinician_names(
        db, (r.clinician_id for r in rows)
    )

    encounters: list[PatientEncounter] = []
    for row in rows:
        latest = notes_by_session.get(row.id)
        encounters.append(
            PatientEncounter(
                session_id=str(row.id),
                clinician_id=str(row.clinician_id),
                clinician_name=names_by_id[str(row.clinician_id)],
                specialty=row.specialty,
                state=(
                    row.state.value
                    if hasattr(row.state, "value")
                    else str(row.state)
                ),
                created_at=row.created_at.isoformat() if row.created_at else "",
                note_version=latest.version if latest is not None else 0,
                note_stage=latest.stage if latest is not None else 0,
                is_approved=latest.is_approved if latest is not None else False,
            )
        )
    return encounters


class ValidateNoteResponse(BaseModel):
    session_id: str
    stage: int
    version: int
    approved: bool
    message: str


@router.post(
    "/patients/notes/{session_id}/validate",
    response_model=ValidateNoteResponse,
)
async def validate_note(
    session_id: uuid.UUID,
    actor: CurrentUser = Depends(require_role(*_CHART_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ValidateNoteResponse:
    """Supervisory sign-off of ANY clinician's note. CLINICAL_ADMIN /
    ADMIN only, and only while the flag is ON.

    Mirrors the owner-scoped ``POST /notes/{id}/approve`` but is NOT
    owner-scoped — it fetches via ``get_session_or_404`` and relies on the
    role gate. Reuses ``approve_note`` (which enforces the #606 invariant:
    never sign off over an unresolved Stage 2 conflict → 409), transitions
    the session to REVIEW_COMPLETE, and writes ``NOTE_VALIDATED`` carrying
    the actor + the target clinician (never the note content or identifier).
    """
    _require_chart_enabled()

    session = await get_session_or_404(db, session_id)

    allowed_states = {
        SessionState.PROCESSING_STAGE2,
        SessionState.REVIEW_COMPLETE,
    }
    if session.state not in allowed_states:
        state_value = (
            session.state.value
            if hasattr(session.state, "value")
            else str(session.state)
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot validate note: session is in {state_value}. "
                "Must be in PROCESSING_STAGE2 or REVIEW_COMPLETE."
            ),
        )

    try:
        approved_note = await approve_note(str(session_id), db)
    except UnresolvedConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    if session.state == SessionState.PROCESSING_STAGE2:
        try:
            await transition_session(
                db, session, SessionState.REVIEW_COMPLETE
            )
        except InvalidTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )

    await write_audit(
        session_id,
        AuditEventType.NOTE_VALIDATED,
        actor_id=str(actor.user_id),
        target_clinician_id=str(session.clinician_id),
        version=approved_note.version,
    )

    return ValidateNoteResponse(
        session_id=str(session_id),
        stage=approved_note.stage,
        version=approved_note.version,
        approved=True,
        message="Note validated (supervisory sign-off).",
    )
