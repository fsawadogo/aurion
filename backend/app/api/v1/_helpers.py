"""Shared helpers for v1 route handlers.

Three small helpers that collapse patterns repeated across the route
modules. Kept in this single file (rather than a package) because each
is a thin wrapper over an existing primitive — no service-layer
abstraction, no DI ceremony.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.models import SessionModel
from app.core.types import ClipMaskingMetadata, MaskingProof, SessionState, UserRole
from app.core.uuids import to_uuid
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser
from app.modules.prompts import ValidationCode, ValidationResult
from app.modules.session.service import get_session

# Roles that bypass row-level ownership checks. Compliance and admin both
# need cross-clinician access — compliance for audit, admin for support.
# Eval team is intentionally excluded: they should only ever see explicitly-
# assigned eval sessions, not arbitrary clinician sessions.
_OWNER_BYPASS_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER}
)


async def get_session_or_404(
    db: AsyncSession, session_id: str | uuid.UUID
) -> SessionModel:
    """Fetch a session by ID or raise 404.

    Accepts either a string (from path params) or a UUID (when callers
    already parsed). Delegates the actual query to
    ``app.modules.session.service.get_session`` — this helper only adds
    the 404 boundary.
    """
    session = await get_session(db, to_uuid(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def assert_owner(session: SessionModel, user: CurrentUser) -> None:
    """Raise 404/403 if ``user`` doesn't own ``session`` and isn't a bypass role.

    Row-level authorization gate for every clinician-facing
    ``/sessions/*`` and ``/notes/*`` route. Before the web portal existed
    this was implicit (iOS only fetches its own sessions), but with web
    as a second consumer the assertion has to be explicit at the route
    layer.

    Bypass roles: ADMIN, COMPLIANCE_OFFICER. Eval team is NOT a bypass —
    they need explicitly-assigned eval rows, not arbitrary clinician
    access.

    Surfaces as 404 (not 403) when the user is a CLINICIAN — leaking the
    existence of another clinician's session is itself a soft PHI
    disclosure. Other non-bypass roles get a 403 because they're at
    least authenticated to some scope; the 404 hide is for clinician-to-
    clinician cross-talk specifically.
    """
    if user.role in _OWNER_BYPASS_ROLES:
        return
    if session.clinician_id != user.user_id:
        if user.role == UserRole.CLINICIAN:
            raise HTTPException(status_code=404, detail="Session not found")
        raise HTTPException(status_code=403, detail="Not session owner")


async def get_owned_session_or_404(
    db: AsyncSession,
    session_id: str | uuid.UUID,
    user: CurrentUser,
) -> SessionModel:
    """Fetch a session by ID, raise 404 if absent, raise 404/403 if not owned.

    Convenience wrapper that combines ``get_session_or_404`` with
    ``assert_owner`` so route handlers don't repeat the same two lines.
    Prefer this over the unscoped ``get_session_or_404`` everywhere a
    clinician-facing route consumes a session by path id.
    """
    session = await get_session_or_404(db, session_id)
    assert_owner(session, user)
    return session


async def write_audit(
    session_id: str | uuid.UUID,
    event_type: AuditEventType | str,
    **fields: Any,
) -> None:
    """Emit an audit event for ``session_id``.

    Wraps ``get_audit_log_service().write_event(...)``. Routes do not
    need the returned record; if a caller does, drop down to the
    service directly.

    ``event_type`` accepts either an ``AuditEventType`` member (the
    normalized path) or a raw string (legacy / data-driven sites such
    as ``get_audit_event_for_state``'s fallback for unknown states).
    Both serialize identically because ``AuditEventType`` is a
    ``StrEnum``.

    Validation against ``ALLOWED_AUDIT_KWARGS`` happens one layer
    down in ``AuditLogService.write_event`` so module-level callers
    that hit the service directly get the same guard (Q-03).
    """
    audit = get_audit_log_service()
    await audit.write_event(session_id=session_id, event_type=event_type, **fields)


def raise_if_validation_failed(validation: ValidationResult) -> None:
    """Raise 400 with the standard prompt-validation detail shape, or no-op.

    The detail dict (``message`` / ``code`` / ``matched_phrase`` /
    ``missing_anchor_group``) is parsed identically by the web client across
    every prompt-save surface — per-physician overrides in ``me_prompts`` and
    admin authoring in ``admin/prompt_studio``. Centralised here once the
    pattern reached a third caller (DRY, §6c).
    """
    if validation.code is not ValidationCode.OK:
        raise HTTPException(
            status_code=400,
            detail={
                "message": validation.message,
                "code": validation.code.value,
                "matched_phrase": validation.matched_phrase,
                "missing_anchor_group": validation.missing_anchor_group,
            },
        )


def require_state(session: SessionModel, *allowed: SessionState) -> None:
    """Raise 409 if ``session.state`` isn't one of ``allowed``.

    The 409 detail follows the existing message shape ("currently: X").
    Used by handlers whose preconditions are state-bound (e.g. only
    operable in PROCESSING_STAGE1 or AWAITING_REVIEW).
    """
    if session.state not in allowed:
        labels = " or ".join(s.value for s in allowed)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Session must be in {labels} state, currently: {session.state.value}"
            ),
        )


def parse_masking_proof(
    frame_type: str,
    masking_status: str,
    faces_detected: int,
    phi_regions_redacted: int,
) -> MaskingProof:
    """Validate the masking proof fields and raise 400 on bad input.

    P0-02 fail-closed guarantee: any frame upload route that accepts
    these fields must call this helper before touching S3.
    """
    try:
        return MaskingProof(
            frame_type=frame_type,
            masking_status=masking_status,
            faces_detected=faces_detected,
            phi_regions_redacted=phi_regions_redacted,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid masking proof: {exc.errors()}"
        ) from exc


def assert_masking_confirmed(masking_confirmed: bool) -> None:
    """P0-01 fail-closed gate for the clip upload path.

    The clip endpoint takes a boolean `masking_confirmed` flag from iOS
    instead of the four-field MaskingProof: every frame in the clip has
    already been validated client-side by `MaskingPipeline.maskClip` and
    a single boolean rides the wire (the per-clip frame counts come on
    `ClipMaskingMetadata`). The boolean must be `True` or the upload is
    rejected before any S3 PutObject runs — same fail-closed contract as
    `parse_masking_proof` for the frame path, just less surface to
    validate. Lives here instead of inline in `clips.py` so any future
    masked-evidence endpoint can reuse it without copy-pasting the
    rejection shape.
    """
    if not masking_confirmed:
        raise HTTPException(
            status_code=400,
            detail=(
                "masking_confirmed must be true — clip rejected before S3 "
                "write (P0-01 fail-closed gate)"
            ),
        )


def parse_clip_masking_metadata(
    frames_total: int,
    frames_with_faces: int,
    faces_blurred: int | None = None,
) -> ClipMaskingMetadata:
    """Validate the per-clip masking metadata and raise 400 on bad input.

    Mirrors `parse_masking_proof` for the clip path. `faces_blurred`
    defaults to `frames_with_faces` because the clip masking pipeline
    fail-closes when any face fails to blur — so a clip that reaches
    this endpoint must have blurred every detected face. iOS may still
    pass `faces_blurred` explicitly for audit-trail completeness, and
    the validator accepts both shapes.

    Raises 400 with the Pydantic error list (same shape as
    `parse_masking_proof`) so the client-side error surface is uniform
    across frame + clip endpoints.
    """
    try:
        return ClipMaskingMetadata(
            frames_total=frames_total,
            frames_with_faces=frames_with_faces,
            faces_blurred=(
                faces_blurred if faces_blurred is not None else frames_with_faces
            ),
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid clip masking metadata: {exc.errors()}",
        ) from exc
