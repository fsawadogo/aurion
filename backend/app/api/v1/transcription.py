"""Transcription API routes.

POST /api/v1/transcription/{session_id} — submit audio for transcription.
No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import SessionState
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.phi_audit.service import scan_transcript_for_phi
from app.modules.session.service import get_session
from app.modules.transcription.service import transcribe_audio
from app.modules.transcription.trigger_classifier import classify_triggers

router = APIRouter(prefix="/transcription", tags=["transcription"])


class TranscriptSegmentResponse(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    speaker_confidence: float | None = None
    is_visual_trigger: bool
    trigger_type: str | None = None


class TranscriptResponse(BaseModel):
    session_id: str
    provider_used: str
    segments: list[TranscriptSegmentResponse]


@router.post("/{session_id}", response_model=TranscriptResponse)
async def submit_transcription(
    session_id: uuid.UUID,
    audio_file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit audio for transcription.

    Pipeline: S3 upload → transcription → trigger classification → PHI audit.
    """
    # Verify session exists and is in the right state
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.state != SessionState.PROCESSING_STAGE1:
        raise HTTPException(
            status_code=409,
            detail=f"Session must be in PROCESSING_STAGE1 state, currently: {session.state.value}",
        )

    audit = get_audit_log_service()

    # Step 1 — Transcribe
    audio_bytes = await audio_file.read()
    transcript = await transcribe_audio(audio_bytes, str(session_id))

    await audit.write_event(
        session_id=str(session_id),
        event_type="transcription_complete",
        provider_used=transcript.provider_used,
        segment_count=len(transcript.segments),
    )

    # Step 2 — Run trigger classifier
    transcript = classify_triggers(transcript)

    # Step 3 — PHI audit
    phi_result = await scan_transcript_for_phi(transcript)
    await audit.write_event(
        session_id=str(session_id),
        event_type="phi_audit_complete",
        phi_detected=phi_result.phi_detected,
    )

    return TranscriptResponse(
        session_id=transcript.session_id,
        provider_used=transcript.provider_used,
        segments=[
            TranscriptSegmentResponse(
                id=s.id,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                text=s.text,
                speaker=s.speaker,
                speaker_confidence=s.speaker_confidence,
                is_visual_trigger=s.is_visual_trigger,
                trigger_type=s.trigger_type,
            )
            for s in transcript.segments
        ],
    )
