"""Export API routes -- DOCX and plain text note export.

No business logic here -- routes call module service functions only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import SessionState
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.export.service import export_note_docx, export_note_plaintext
from app.modules.note_gen.service import get_latest_note, is_note_approved
from app.modules.session.service import (
    InvalidTransitionError,
    get_session,
    transition_session,
)

router = APIRouter(prefix="/notes", tags=["export"])


@router.post("/{session_id}/export")
async def export_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export the approved note as a DOCX file.

    The session must be in REVIEW_COMPLETE state (note approved).
    After export, the session transitions to EXPORTED and the
    cleanup pipeline is triggered (frame purge + eval migration).

    Returns the DOCX file as a downloadable attachment.
    """
    # Validate session exists
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    # Session must be in REVIEW_COMPLETE to export
    if session.state != SessionState.REVIEW_COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot export: session is in {session.state.value}. "
                f"Must be in REVIEW_COMPLETE (note approved)."
            ),
        )

    # Verify the note is approved
    approved = await is_note_approved(str(session_id), db)
    if not approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot export: note has not been approved yet.",
        )

    # Get the latest (approved) note
    note = await get_latest_note(str(session_id), db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No note found for this session.",
        )

    # Generate DOCX
    docx_bytes = await export_note_docx(str(session_id), note, db)

    # Transition session to EXPORTED
    try:
        await transition_session(db, session, SessionState.EXPORTED)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # Return DOCX as downloadable file
    filename = f"aurion_note_{session_id}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
