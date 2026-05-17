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

from app.core.models import SessionModel
from app.core.types import MaskingProof, SessionState
from app.modules.audit_log.service import get_audit_log_service
from app.modules.session.service import get_session


async def get_session_or_404(
    db: AsyncSession, session_id: str | uuid.UUID
) -> SessionModel:
    """Fetch a session by ID or raise 404.

    Accepts either a string (from path params) or a UUID (when callers
    already parsed). Delegates the actual query to
    ``app.modules.session.service.get_session`` — this helper only adds
    the 404 boundary.
    """
    sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    session = await get_session(db, sid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def write_audit(
    session_id: str | uuid.UUID,
    event_type: str,
    **fields: Any,
) -> None:
    """Emit an audit event for ``session_id``.

    Wraps ``get_audit_log_service().write_event(...)``. Routes do not
    need the returned record; if a caller does, drop down to the
    service directly.
    """
    audit = get_audit_log_service()
    await audit.write_event(session_id=session_id, event_type=event_type, **fields)


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
