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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, require_state, write_audit
from app.api.v1.websocket import notify_stage1_delivered
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import PilotMetricsModel, TranscriptModel
from app.core.types import SessionState, Transcript
from app.modules.alerts.service import AlertSeverity, try_publish_alert
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.cleanup.service import purge_audio_for_session
from app.modules.config.appconfig_client import get_config
from app.modules.note_gen.service import EmptyTranscriptError, generate_stage1_note
from app.modules.phi_audit.service import scan_transcript_for_phi
from app.modules.session.service import (
    InvalidTransitionError,
    transition_session,
)
from app.modules.transcription.service import merge_transcripts, transcribe_audio
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


async def _purge_raw_audio_if_not_retained(session_id) -> None:
    """Spec-timing raw-audio purge (#605): delete the session's raw audio
    in-band right after a SUCCESSFUL transcription — unless the media-review
    retention window is on.

    The MVP Scope Definition requires raw audio deleted <1hr post-
    transcription. Audio is the spine: once the transcript exists the raw
    audio has served its purpose, so in the default posture we delete it
    immediately rather than waiting on the whole-day S3 lifecycle TTL.

    When ``media_review_retention_enabled`` is ON (opt-in, compliance-gated,
    #338) the audio is instead KEPT for the replay/download window and the S3
    lifecycle TTL is the max-window backstop — so this no-ops.

    Fail-soft: a purge hiccup must never turn a delivered note into a failed
    request; the S3 lifecycle TTL backstops any object left behind. The
    underlying ``purge_audio_for_session`` writes its own immutable
    ``AUDIO_PURGED`` audit row (bucket + count, never a key or body).
    """
    if get_config().feature_flags.media_review_retention_enabled:
        return
    try:
        await purge_audio_for_session(str(session_id))
    except Exception:
        logger.warning(
            "In-band raw-audio purge failed for session=%s — the S3 "
            "lifecycle TTL will backstop it",
            str(session_id)[:8],
            exc_info=True,
        )


async def run_stage1(db: AsyncSession, session, audio_bytes: bytes):
    """Run the Stage 1 pipeline for a session and return the transcript.

    Extracted verbatim from the transcription route so BOTH the HTTP path
    (``submit_transcription``) and the web-portal video-import orchestrator
    (``api/v1/video_import``) drive identical Stage 1 behaviour (DRY §6c) —
    transcribe → trigger-classify → persist → PHI scan → note gen →
    AWAITING_REVIEW → latency metric → WebSocket push.

    Precondition: ``session`` is in ``PROCESSING_STAGE1`` (the caller owns
    that transition — the route via iOS /stop, the orchestrator explicitly).
    Raises the same ``HTTPException``s as before (422 empty-transcript, 500
    note-gen failure, 409 bad transition); the orchestrator catches them and
    fails the job, the route re-raises them to the client.

    Returns the (trigger-classified) ``Transcript`` so the route can build
    its ``TranscriptResponse``.
    """
    session_id = session.id

    # M-06: end-to-end Stage 1 latency. Measured from pipeline-entry so we
    # capture the full backend processing window.
    stage1_start = time.monotonic()

    transcript = await transcribe_audio(audio_bytes, str(session_id))

    await write_audit(
        session_id,
        AuditEventType.TRANSCRIPTION_COMPLETE,
        provider_used=transcript.provider_used,
        segment_count=len(transcript.segments),
    )

    transcript = await classify_triggers(transcript)

    # Persist the transcript so the Stage 2 vision pipeline can find
    # trigger-flagged segments after /approve-stage1 fires. Upsert.
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
        AuditEventType.PHI_AUDIT_COMPLETE,
        phi_detected=phi_result.phi_detected,
    )

    # #275 — deserialize the encounter participant snapshot off the row so
    # Stage 1 can attribute statements by role/name. Defensive parse.
    participants: list[dict] = []
    raw_participants = getattr(session, "participants_json", None)
    if raw_participants:
        try:
            decoded = json.loads(raw_participants)
            if isinstance(decoded, list):
                participants = decoded
        except (TypeError, ValueError):
            logger.warning(
                "Failed to decode participants_json for session=%s — "
                "Stage 1 proceeds without participant attribution",
                session_id,
            )

    try:
        stage1_note = await generate_stage1_note(
            transcript=transcript,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
            output_language=session.output_language,
            template_key=getattr(session, "template_key", None),
            custom_template_id=getattr(session, "custom_template_id", None),
            participants=participants,
            encounter_context=session.encounter_context,
        )
    except EmptyTranscriptError as exc:
        try:
            await transition_session(
                db, session, SessionState.STAGE1_FAILED_NO_AUDIO
            )
        except InvalidTransitionError:
            logger.warning(
                "Stage 1 guard fired but session=%s could not transition "
                "to STAGE1_FAILED_NO_AUDIO from state=%s",
                session_id,
                session.state.value,
            )
        await write_audit(
            session_id, AuditEventType.STAGE1_FAILED, reason=exc.reason
        )
        raise HTTPException(
            status_code=422,
            detail={
                "reason": exc.reason,
                "message": exc.human_message,
            },
        )
    except Exception as exc:
        reason = str(exc)[:200]
        # Move the session to the terminal STAGE1_FAILED state. Without this
        # the session was left in PROCESSING_STAGE1 forever — a provider parse
        # error / rate-limit / timeout stranded it as perpetually "processing"
        # with no recovery once the iOS app's in-memory recording was gone.
        # Mirrors the empty-transcript path's transition to its own terminal
        # failed state.
        try:
            await transition_session(db, session, SessionState.STAGE1_FAILED)
        except InvalidTransitionError:
            logger.warning(
                "Stage 1 generation failed but session=%s could not transition "
                "to STAGE1_FAILED from state=%s",
                session_id,
                session.state.value,
            )
        await write_audit(session_id, AuditEventType.STAGE1_FAILED, reason=reason)
        await try_publish_alert(
            alert_type=AuditEventType.STAGE1_FAILED.value,
            severity=AlertSeverity.CRITICAL,
            source="transcription_service",
            message="Stage 1 note generation failed",
            metadata={"session_id": str(session_id), "reason": reason},
        )
        raise HTTPException(
            status_code=500,
            detail=f"Stage 1 note generation failed: {exc}",
        )

    # Empty-note guardrail (#280): structurally-valid but zero populated
    # required sections — delivered, not failed, but must be visible.
    if stage1_note.completeness_score <= 0.0:
        await write_audit(
            session_id,
            AuditEventType.STAGE1_EMPTY_NOTE,
            segment_count=len(transcript.segments),
            transcript_char_count=sum(len(s.text) for s in transcript.segments),
            completeness=stage1_note.completeness_score,
        )

    try:
        await transition_session(db, session, SessionState.AWAITING_REVIEW)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    stage1_latency_ms = int((time.monotonic() - stage1_start) * 1000)
    await _record_stage1_latency(db, session, stage1_latency_ms)

    await write_audit(
        session_id,
        AuditEventType.STAGE1_DELIVERED,
        stage1_latency_ms=stage1_latency_ms,
    )

    # Push the note to any connected WebSocket client. Self-swallows so a
    # WS hiccup can never turn a delivered note into a failed request.
    await notify_stage1_delivered(str(session_id), stage1_note)

    # #605 — raw audio has served its purpose once the transcript + note are
    # delivered; purge it in-band (<1hr) unless the replay window is on. Placed
    # here (after full Stage-1 success) so a transcription/note-gen failure —
    # which raises above and rolls the request back — keeps the audio for retry.
    await _purge_raw_audio_if_not_retained(session_id)

    return transcript


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
    session = await get_owned_session_or_404(db, session_id, user)
    require_state(session, SessionState.PROCESSING_STAGE1)

    # The Stage 1 pipeline is shared with the web-portal video-import
    # orchestrator (DRY §6c). Behaviour is unchanged: this route owns the
    # HTTP boundary (ownership + state precondition + multipart read), the
    # shared ``run_stage1`` owns the pipeline + state transition + delivery.
    audio_bytes = await audio_file.read()
    transcript = await run_stage1(db, session, audio_bytes)

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


# ── Resume recording (append a follow-up clip → merge → regenerate) ────────


class AppendRecordingResponse(BaseModel):
    version: int
    stage: int
    completeness_score: float
    provider_used: str
    added_segments: int
    total_segments: int


@router.post("/{session_id}/append", response_model=AppendRecordingResponse)
async def append_recording(
    session_id: uuid.UUID,
    audio_file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppendRecordingResponse:
    """Resume-recording (note-Options phase 4): transcribe a follow-up clip,
    MERGE it onto the stored transcript, and regenerate the note covering both
    — no re-record of the first clip, no state-machine change.

    Deliberately bypasses ``run_stage1`` / the PROCESSING_STAGE1 gate: the
    merge is in-memory and we reuse the regenerate pattern (no state
    precondition), so an AWAITING_REVIEW / REVIEW_COMPLETE encounter can gain a
    second clip without a back-edge to RECORDING. Owner-scoped; gated on
    ``note_options_enabled``. Consent is already satisfied on the row.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    if not get_config().feature_flags.note_options_enabled:
        raise HTTPException(
            status_code=403, detail="Resume recording is not enabled."
        )

    # Need an existing transcript to append onto.
    row = (
        await db.execute(
            select(TranscriptModel).where(
                TranscriptModel.session_id == session_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No transcript for this session to append to.",
        )
    existing = Transcript(**json.loads(row.transcript_json))

    # Transcribe the NEW clip ONLY — never re-transcribe clip 1.
    audio_bytes = await audio_file.read()
    addition = await transcribe_audio(audio_bytes, str(session_id))
    if not addition.segments:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "empty_addition",
                "message": "The follow-up recording had no speech to add.",
            },
        )

    # Merge in memory (offset + renumber), re-flag triggers, persist once.
    merged = merge_transcripts(existing, addition)
    merged = await classify_triggers(merged)
    row.provider_used = merged.provider_used
    row.transcript_json = merged.model_dump_json()
    await db.flush()

    # Participant snapshot (mirror run_stage1's attribution wiring).
    participants: list[dict] = []
    raw_participants = getattr(session, "participants_json", None)
    if raw_participants:
        try:
            decoded = json.loads(raw_participants)
            if isinstance(decoded, list):
                participants = decoded
        except (TypeError, ValueError):
            pass

    try:
        note = await generate_stage1_note(
            transcript=merged,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
            output_language=session.output_language,
            template_key=getattr(session, "template_key", None),
            custom_template_id=getattr(session, "custom_template_id", None),
            participants=participants,
            encounter_context=session.encounter_context,
        )
    except EmptyTranscriptError:
        raise HTTPException(
            status_code=422, detail="The merged transcript is empty."
        )

    await write_audit(
        session_id,
        AuditEventType.RECORDING_APPENDED,
        actor_id=str(user.user_id),
        version=note.version,
        provider_used=note.provider_used,
        added_segments=len(addition.segments),
    )
    await db.commit()

    # #605 — the appended clip's raw audio was uploaded + transcribed here;
    # purge all of the session's raw audio in-band (<1hr) once the merged
    # transcript is durably committed, unless the replay window is on. Post-
    # commit, so there is no rollback-vs-purge race on this path.
    await _purge_raw_audio_if_not_retained(session_id)

    return AppendRecordingResponse(
        version=note.version,
        stage=note.stage,
        completeness_score=note.completeness_score,
        provider_used=note.provider_used,
        added_segments=len(addition.segments),
        total_segments=len(merged.segments),
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
        AuditEventType.SPEAKER_TAGS_APPLIED,
        segments_updated=updated,
        segments_unknown=len(unknown),
    )

    return SpeakerTagApplyResponse(
        session_id=str(session_id),
        segments_updated=updated,
        segments_unknown=unknown,
    )
