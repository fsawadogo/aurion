"""Export API routes -- DOCX and plain text note export.

No business logic here -- routes call module service functions only.

Two flavours exist side-by-side:
  - POST /notes/{id}/export — server-side generation, used by the web
    portal where a download URL is the natural delivery.
  - POST /notes/{id}/export-audit — iOS calls this AFTER generating the
    bytes on-device (M-11). No file payload crosses the wire; the
    endpoint exists solely to advance state and write the audit event so
    cleanup fires on the same lifecycle hook as web export.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import SessionState
from app.api.v1._helpers import get_session_or_404, write_audit
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.export.service import export_note_docx, export_note_plaintext
from app.modules.note_gen.service import get_latest_note, is_note_approved
from app.modules.session.service import (
    InvalidTransitionError,
    transition_session,
)

router = APIRouter(prefix="/notes", tags=["export"])


class ExportAuditRequest(BaseModel):
    """Body for the on-device export audit. `format` is what the client
    actually generated; `bytes_produced` is the local file size for the
    PHI masking report."""

    format: Literal["docx", "plain_text"]
    bytes_produced: int


class ExportAuditResponse(BaseModel):
    session_id: str
    session_state: str
    audit_written: bool


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
    session = await get_session_or_404(db, session_id)
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


@router.post("/{session_id}/export-audit", response_model=ExportAuditResponse)
async def record_on_device_export(
    session_id: uuid.UUID,
    body: ExportAuditRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record an on-device export. iOS calls this AFTER successfully
    generating the file locally — no bytes cross the wire here.

    Same state preconditions as `/export`: session must be in
    REVIEW_COMPLETE with an approved note. On success the session
    transitions to EXPORTED so the cleanup pipeline can fire.
    """
    session = await get_session_or_404(db, session_id)

    if session.state not in {SessionState.REVIEW_COMPLETE, SessionState.EXPORTED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot record export: session is in {session.state.value}. "
                f"Must be in REVIEW_COMPLETE."
            ),
        )

    approved = await is_note_approved(str(session_id), db)
    if not approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot record export: note has not been approved yet.",
        )

    # Idempotent transition — already-EXPORTED sessions still get the
    # audit row written so duplicate exports (e.g. user re-shares the
    # locally-cached file) are visible to compliance.
    if session.state == SessionState.REVIEW_COMPLETE:
        try:
            await transition_session(db, session, SessionState.EXPORTED)
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    await write_audit(
        session_id,
        "note_exported",
        format=body.format,
        bytes_produced=body.bytes_produced,
        origin="on_device",
    )

    return ExportAuditResponse(
        session_id=str(session_id),
        session_state=session.state.value,
        audit_written=True,
    )
