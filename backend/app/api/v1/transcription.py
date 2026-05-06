"""Transcription API routes.

POST /api/v1/transcription/{session_id} — submit audio for transcription.
No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.core.models import TranscriptModel
from app.core.types import SessionState
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.note_gen.service import generate_stage1_note
from app.modules.phi_audit.service import scan_transcript_for_phi
from app.modules.session.service import (
    InvalidTransitionError,
    get_session,
    transition_session,
)
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

    # Step 2b — Persist the transcript so the Stage 2 vision pipeline can find
    # trigger-flagged segments after /approve-stage1 fires (which happens in
    # a separate request). Upsert: re-uploads overwrite the prior transcript.
    existing = await db.execute(
        select(TranscriptModel).where(TranscriptModel.session_id == session_id)
    )
    row = existing.scalar_one_or_none()
    if row is None:
        db.add(
            TranscriptModel(
                session_id=session_id,
                provider_used=transcript.provider_used,
                transcript_json=transcript.model_dump_json(),
            )
        )
    else:
        row.provider_used = transcript.provider_used
        row.transcript_json = transcript.model_dump_json()
    await db.flush()

    # Step 3 — PHI audit
    phi_result = await scan_transcript_for_phi(transcript)
    await audit.write_event(
        session_id=str(session_id),
        event_type="phi_audit_complete",
        phi_detected=phi_result.phi_detected,
    )

    # Step 4 — Generate Stage 1 note from transcript and transition the session
    # to AWAITING_REVIEW. On failure we leave the session in PROCESSING_STAGE1
    # so a retry of /transcription/{id} can pick up where it left off.
    try:
        await generate_stage1_note(
            transcript=transcript,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
        )
    except Exception as exc:
        await audit.write_event(
            session_id=str(session_id),
            event_type="stage1_failed",
            reason=str(exc)[:200],
        )
        raise HTTPException(
            status_code=500,
            detail=f"Stage 1 note generation failed: {exc}",
        )

    try:
        await transition_session(db, session, SessionState.AWAITING_REVIEW)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    await audit.write_event(
        session_id=str(session_id),
        event_type="stage1_delivered",
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
