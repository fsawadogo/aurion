"""Vision API routes — Stage 2 frame processing.

POST /api/v1/vision/{session_id} — process frames for a session.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import SessionState
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.session.service import get_session

router = APIRouter(prefix="/vision", tags=["vision"])


class FrameCaptionResponse(BaseModel):
    frame_id: str
    session_id: str
    timestamp_ms: int
    audio_anchor_id: str
    provider_used: str
    visual_description: str
    confidence: str
    confidence_reason: str
    conflict_flag: bool
    conflict_detail: Optional[str] = None
    integration_status: str


class VisionProcessingResponse(BaseModel):
    session_id: str
    frames_processed: int
    frames_discarded: int
    enriches_count: int
    repeats_count: int
    conflicts_count: int
    captions: list[FrameCaptionResponse]


@router.post("/{session_id}", response_model=VisionProcessingResponse)
async def process_vision_frames(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Process masked frames for a session through the vision pipeline."""
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.state != SessionState.PROCESSING_STAGE2:
        raise HTTPException(
            status_code=409,
            detail=f"Session must be in PROCESSING_STAGE2 state, currently: {session.state.value}",
        )

    audit = get_audit_log_service()

    # For now, return empty results — frames will be submitted when
    # the full pipeline is integrated
    await audit.write_event(
        session_id=str(session_id),
        event_type="stage2_started",
    )

    return VisionProcessingResponse(
        session_id=str(session_id),
        frames_processed=0,
        frames_discarded=0,
        enriches_count=0,
        repeats_count=0,
        conflicts_count=0,
        captions=[],
    )
