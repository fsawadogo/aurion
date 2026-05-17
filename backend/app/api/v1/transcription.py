"""Transcription API routes.

POST /api/v1/transcription/{session_id} — submit audio for transcription.
PATCH /api/v1/transcription/{session_id}/speakers — apply on-device
speaker tags (physician/other) to persisted transcript segments.

No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.core.models import PilotMetricsModel, TranscriptModel
from app.core.types import SessionState
from app.api.v1._helpers import get_session_or_404, require_state, write_audit
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.note_gen.service import generate_stage1_note
from app.modules.phi_audit.service import scan_transcript_for_phi
from app.modules.session.service import (
    InvalidTransitionError,
    transition_session,
)
from app.modules.transcription.service import transcribe_audio
from app.modules.transcription.trigger_classifier import classify_triggers

logger = logging.getLogger("aurion.api.transcription")

router = APIRouter(prefix="/transcription", tags=["transcription"])


Speaker = Literal["physician", "other"]


async def _record_stage1_latency(
    db: AsyncSession,
    session,  # SessionModel — imported lazily to avoid a circular import
    latency_ms: int,
) -> None:
    """Upsert `stage1_latency_ms` into the per-session pilot_metrics row.
    Non-fatal: metrics are passive and must never block Stage 1 delivery
    (CLAUDE.md §"Passive Data Collection").
    """
    try:
        row = (
            await db.execute(
                select(PilotMetricsModel).where(PilotMetricsModel.session_id == session.id)
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                PilotMetricsModel(
                    session_id=session.id,
                    clinician_id=session.clinician_id,
                    specialty=session.specialty,
                    stage1_latency_ms=latency_ms,
                )
            )
        else:
            row.stage1_latency_ms = latency_ms
        await db.flush()
    except Exception as exc:
        logger.warning(
            "Failed to record stage1_latency_ms for session=%s: %s",
            session.id, exc,
        )


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
    session = await get_session_or_404(db, session_id)
    require_state(session, SessionState.PROCESSING_STAGE1)

    # M-06: end-to-end Stage 1 latency. Measured from request-entry rather
    # than the recording_stopped audit event so we capture the full backend
    # processing window; iOS still measures the user-facing record-stop →
    # note-delivered window separately when reporting metrics.
    stage1_start = time.monotonic()

    audio_bytes = await audio_file.read()
    transcript = await transcribe_audio(audio_bytes, str(session_id))

    await write_audit(
        session_id,
        "transcription_complete",
        provider_used=transcript.provider_used,
        segment_count=len(transcript.segments),
    )

    transcript = classify_triggers(transcript)

    # Persist the transcript so the Stage 2 vision pipeline can find
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

    phi_result = await scan_transcript_for_phi(transcript)
    await write_audit(
        session_id,
        "phi_audit_complete",
        phi_detected=phi_result.phi_detected,
    )

    # On failure we leave the session in PROCESSING_STAGE1 so a retry of
    # /transcription/{id} can pick up where it left off.
    try:
        await generate_stage1_note(
            transcript=transcript,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
        )
    except Exception as exc:
        await write_audit(session_id, "stage1_failed", reason=str(exc)[:200])
        raise HTTPException(
            status_code=500,
            detail=f"Stage 1 note generation failed: {exc}",
        )

    try:
        await transition_session(db, session, SessionState.AWAITING_REVIEW)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    stage1_latency_ms = int((time.monotonic() - stage1_start) * 1000)
    await _record_stage1_latency(db, session, stage1_latency_ms)

    await write_audit(
        session_id,
        "stage1_delivered",
        stage1_latency_ms=stage1_latency_ms,
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


# ═══════════════════════════════════════════════════════════════════════════
# Speaker Tag PATCH — M-01 on-device speaker tagging
# ═══════════════════════════════════════════════════════════════════════════


class SpeakerTag(BaseModel):
    """A single on-device speaker tag. Aurion does not perform multi-speaker
    diarization (CLAUDE.md §"What NOT to Build") — speaker is strictly
    {physician, other}. The biometric embedding stays in the device's
    Keychain; only the label and confidence cross the wire.
    """

    segment_id: str = Field(..., min_length=1)
    speaker: Speaker
    confidence: float = Field(..., ge=0.0, le=1.0)


class SpeakerTagBatch(BaseModel):
    tags: list[SpeakerTag]


class SpeakerTagApplyResponse(BaseModel):
    session_id: str
    segments_updated: int
    segments_unknown: list[str]


@router.patch("/{session_id}/speakers", response_model=SpeakerTagApplyResponse)
async def apply_speaker_tags(
    session_id: uuid.UUID,
    batch: SpeakerTagBatch,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply on-device speaker tags to the persisted transcript.

    iOS runs `SpeakerSeparation.tagSpeaker` locally against each
    transcript segment using the physician's voice embedding (stored in
    Keychain, never transmitted). This endpoint records the resulting
    labels on the server-side transcript so Stage 1/2 note generation
    can use them.

    Returns the number of segments updated and any unknown segment IDs
    so the client can detect drift between local and persisted state.
    """
    row = (
        await db.execute(
            select(TranscriptModel).where(TranscriptModel.session_id == session_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Transcript not found for session")

    try:
        transcript = json.loads(row.transcript_json)
    except json.JSONDecodeError as exc:
        logger.error("Corrupt transcript for session=%s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Persisted transcript is corrupt")

    segments = transcript.get("segments", [])
    by_id = {seg.get("id"): seg for seg in segments}
    updated = 0
    unknown: list[str] = []

    for tag in batch.tags:
        seg = by_id.get(tag.segment_id)
        if seg is None:
            unknown.append(tag.segment_id)
            continue
        seg["speaker"] = tag.speaker
        seg["speaker_confidence"] = tag.confidence
        updated += 1

    row.transcript_json = json.dumps(transcript)
    await db.flush()

    await write_audit(
        session_id,
        "speaker_tags_applied",
        segments_updated=updated,
        segments_unknown=len(unknown),
    )

    return SpeakerTagApplyResponse(
        session_id=str(session_id),
        segments_updated=updated,
        segments_unknown=unknown,
    )
