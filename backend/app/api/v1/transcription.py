"""Transcription API routes.

POST /api/v1/transcription/{session_id} — submit audio for transcription.
PATCH /api/v1/transcription/{session_id}/speakers — apply on-device
speaker tags (physician/other) to persisted transcript segments.

No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, require_state, write_audit
from app.api.v1.websocket import notify_stage1_delivered
from app.core.audit_events import AuditEventType
from app.core.background import spawn_background_task
from app.core.database import get_db
from app.core.models import PilotMetricsModel, TranscriptModel
from app.core.types import Note, SessionState, Transcript
from app.modules.alerts.detectors import sla_stage1_ms
from app.modules.alerts.service import AlertSeverity, try_publish_alert
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.cleanup.service import purge_audio_for_session
from app.modules.config.appconfig_client import get_config
from app.modules.note_gen.service import (
    EmptyTranscriptError,
    Stage1DeadlineExceededError,
    _resolve_stage1_template,
    build_and_persist_minimal_note,
    generate_stage1_note,
)
from app.modules.phi_audit.service import scan_transcript_for_phi
from app.modules.session.service import (
    InvalidTransitionError,
    stored_template_pin,
    transition_session,
)
from app.modules.transcription.service import merge_transcripts, transcribe_audio
from app.modules.transcription.trigger_classifier import classify_triggers

logger = logging.getLogger("aurion.api.transcription")

_STAGE1_FAILURE_REASON = "stage1_generation_failed"
_STAGE1_FAILURE_MESSAGE = "Stage 1 note generation failed."
_STAGE1_DEADLINE_MESSAGE = "Stage 1 processing timed out."
_TRANSCRIPTION_FAILURE_REASON = "transcription_failed"
_TRANSCRIPTION_FAILURE_MESSAGE = "Transcription failed; the session could not be processed."


@dataclass
class _Stage1Progress:
    """In-memory handoff used to resolve commit-vs-timeout ambiguity."""

    transcript: Transcript | None = None
    note: Note | None = None
    latency_ms: int | None = None


async def _raise_stage1_failure(
    db: AsyncSession,
    session,
    *,
    reason: str,
    public_message: str,
) -> NoReturn:
    """Durably fail Stage 1 using bounded, PHI-free public/audit fields."""

    try:
        await transition_session(db, session, SessionState.STAGE1_FAILED)
    except InvalidTransitionError:
        logger.warning(
            "Stage 1 failed but session=%s could not transition from state=%s",
            session.id,
            session.state.value,
        )
    else:
        # ``get_db`` rolls back when the HTTPException below leaves the route.
        # Commit the terminal state first so PROCESSING_STAGE1 cannot survive a
        # handled provider/deadline failure.
        await db.commit()

    await write_audit(session.id, AuditEventType.STAGE1_FAILED, reason=reason)
    await try_publish_alert(
        alert_type=AuditEventType.STAGE1_FAILED.value,
        severity=AlertSeverity.CRITICAL,
        source="transcription_service",
        message=public_message,
        metadata={"session_id": str(session.id), "reason": reason},
    )
    raise HTTPException(status_code=500, detail=public_message) from None


async def _handle_stage1_owner_timeout(
    db: AsyncSession,
    session,
) -> bool:
    """Resolve the durable winner after cancellation at the commit boundary.

    Returns ``True`` when the success commit reached the database before the
    timeout cancellation. Otherwise records one durable Stage 1 failure and
    raises the stable public error.
    """

    # Owner expiry may interrupt execute/flush/commit. SQLAlchemy requires a
    # rollback before the session can safely be reused; refresh reloads the
    # pre-run PROCESSING_STAGE1 row after rollback expires ORM attributes.
    await db.rollback()
    await db.refresh(session)
    if session.state == SessionState.AWAITING_REVIEW:
        logger.info(
            "Stage 1 success commit won the owner-timeout race: session=%s",
            str(session.id)[:8],
        )
        return True
    await _raise_stage1_failure(
        db,
        session,
        reason=Stage1DeadlineExceededError.reason,
        public_message=_STAGE1_DEADLINE_MESSAGE,
    )


async def _finish_stage1_after_commit(
    session_id: uuid.UUID,
    stage1_note,
    stage1_latency_ms: int,
) -> None:
    """Run non-transactional delivery effects after durable Stage 1 success.

    The database commit is the Stage 1 ownership boundary. These effects must
    never turn an already-delivered note into a failure, and raw audio must
    never be purged before that commit. The retained background task lets the
    HTTP response respect the owner SLA if DynamoDB, WebSocket delivery, or S3
    cleanup is slow, while the normal fast path is still awaited below.
    """

    try:
        await write_audit(
            session_id,
            AuditEventType.STAGE1_DELIVERED,
            stage1_latency_ms=stage1_latency_ms,
        )
    except Exception as exc:  # noqa: BLE001 - committed success is immutable
        logger.error(
            "Post-commit Stage 1 audit failed: session=%s error_type=%s",
            str(session_id)[:8],
            type(exc).__name__,
        )

    try:
        await notify_stage1_delivered(str(session_id), stage1_note)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.warning(
            "Post-commit Stage 1 notification failed: session=%s error_type=%s",
            str(session_id)[:8],
            type(exc).__name__,
        )

    await _purge_raw_audio_if_not_retained(session_id)

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


async def _resolve_trigger_template(db: AsyncSession, session):
    """The session's Template for trigger classification, or None.

    Uses the SAME pin the note generator resolves from, so classification and
    generation can never disagree about which template the session is on.

    Returns None on any failure, which makes `classify_triggers` fall back to
    its global defaults — the behaviour before the template was wired in. A
    stale custom-template binding must degrade trigger coverage, never fail
    Stage 1: the note is still produced, just with generic visual cues.
    """
    try:
        pinned_key, pinned_custom_id = stored_template_pin(session)
        return await _resolve_stage1_template(
            template_key=pinned_key,
            specialty=session.specialty,
            custom_template_id=pinned_custom_id,
            db=db,
        )
    except Exception:  # noqa: BLE001 — coverage degradation, never a hard fail
        logger.warning(
            "Trigger-template resolution failed for session=%s — "
            "falling back to default trigger keywords",
            str(session.id)[:8],
            exc_info=True,
        )
        return None


async def run_stage1(
    db: AsyncSession,
    session,
    audio_bytes: bytes,
    *,
    allow_visual_only: bool = False,
):
    """Run the complete Stage 1 owner under its configured wall clock."""

    stage1_start = time.monotonic()
    stage1_deadline_at = (
        asyncio.get_running_loop().time() + (sla_stage1_ms() / 1000.0)
    )
    progress = _Stage1Progress()
    timeout = asyncio.timeout_at(stage1_deadline_at)
    try:
        async with timeout:
            await _run_stage1_within_owner(
                db,
                session,
                audio_bytes,
                allow_visual_only=allow_visual_only,
                stage1_start=stage1_start,
                stage1_deadline_at=stage1_deadline_at,
                progress=progress,
            )
    except TimeoutError:
        if not timeout.expired():
            raise
        success_committed = await _handle_stage1_owner_timeout(db, session)
        if not success_committed:
            raise AssertionError("unreachable Stage 1 timeout outcome")

    # A committed success always populates this handoff before commit begins.
    # If that invariant breaks, fail closed without scheduling an audio purge.
    if (
        progress.transcript is None
        or progress.note is None
        or progress.latency_ms is None
    ):
        raise RuntimeError("Stage 1 committed without a complete success handoff")

    # The note/session transaction is committed inside the owner deadline.
    # From this point onward it is a durable success and must never be rewritten
    # as failed. Give the normal fast post-commit path the remaining SLA budget;
    # shield it so a slow external dependency continues in the retained task
    # after the doctor response returns at the deadline.
    post_commit_task = spawn_background_task(
        _finish_stage1_after_commit(
            session.id,
            progress.note,
            progress.latency_ms,
        ),
        name="stage1-post-commit",
    )
    remaining_seconds = stage1_deadline_at - asyncio.get_running_loop().time()
    if remaining_seconds > 0:
        try:
            await asyncio.wait_for(
                asyncio.shield(post_commit_task),
                timeout=remaining_seconds,
            )
        except TimeoutError:
            logger.warning(
                "Stage 1 post-commit effects exceeded the owner budget and "
                "will finish in background: session=%s",
                str(session.id)[:8],
            )
    return progress.transcript


async def _run_stage1_within_owner(
    db: AsyncSession,
    session,
    audio_bytes: bytes,
    *,
    allow_visual_only: bool,
    stage1_start: float,
    stage1_deadline_at: float,
    progress: _Stage1Progress,
) -> None:
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

    Populates ``progress`` before the durable commit so the outer owner can
    resolve a commit-versus-timeout race without inventing a second outcome.
    """
    session_id = session.id

    try:
        transcript = await transcribe_audio(audio_bytes, str(session_id))
    except Exception:
        await _raise_stage1_failure(
            db,
            session,
            reason=_TRANSCRIPTION_FAILURE_REASON,
            public_message=_TRANSCRIPTION_FAILURE_MESSAGE,
        )

    await write_audit(
        session_id,
        AuditEventType.TRANSCRIPTION_COMPLETE,
        provider_used=transcript.provider_used,
        segment_count=len(transcript.segments),
    )

    # Classify against THIS session's template, not the global defaults.
    # `classify_triggers` has always accepted a template, but no caller ever
    # passed one — so every curated `visual_trigger_keywords` list in the
    # built-in and custom templates was dead weight, and only
    # DEFAULT_TRIGGER_CATEGORIES ever ran. The defaults cover the generic
    # cues ("x-ray", "range of motion") but none of the specialty vocabulary
    # (Hawkins, Neer, Lachman; the plastics wound terms), so segments that
    # should have anchored a frame never flagged, and the physical-exam and
    # imaging frames were never extracted to enrich the note.
    #
    # Resolved with the same pin the note generator uses below, so trigger
    # classification and note generation can never disagree about which
    # template the session is on. Best-effort: a resolution failure falls
    # back to the defaults rather than failing Stage 1 over it.
    template_for_triggers = await _resolve_trigger_template(db, session)
    transcript = await classify_triggers(transcript, template=template_for_triggers)

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

    pinned_key, pinned_custom_id = stored_template_pin(session)
    try:
        stage1_note = await generate_stage1_note(
            transcript=transcript,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
            output_language=session.output_language,
            template_key=pinned_key,
            custom_template_id=pinned_custom_id,
            participants=participants,
            encounter_context=session.encounter_context,
            deadline_at=stage1_deadline_at,
            deadline_owned_externally=True,
        )
    except EmptyTranscriptError as exc:
        # Standalone-visual path: the audio is empty/thin, but this is a video
        # import and the flag is on — DON'T hard-fail. Lay down a minimal empty
        # note so the orchestrator proceeds to frame extraction + Stage-2 vision,
        # which populate the sections from the video (cited to their frame). No
        # generative call was made (the guard fired first), so there is zero
        # hallucination surface — every section stays not_captured until vision.
        if allow_visual_only:
            await write_audit(
                session_id,
                AuditEventType.STAGE1_SKIPPED_NO_TRANSCRIPT,
                reason=exc.reason,
            )
            stage1_note = await build_and_persist_minimal_note(
                specialty=session.specialty,
                session_id=str(session_id),
                db=db,
                template_key=pinned_key,
                custom_template_id=pinned_custom_id,
            )
            logger.info(
                "Empty transcript on standalone-visual import — minimal note "
                "created, continuing to vision: session=%s reason=%s",
                session_id,
                exc.reason,
            )
        else:
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
            else:
                # The request raises 422 below, so get_db would otherwise roll
                # this flush back and leave the session processing forever.
                await db.commit()
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
        deadline_exceeded = isinstance(exc, Stage1DeadlineExceededError)
        reason = (
            Stage1DeadlineExceededError.reason
            if deadline_exceeded
            else _STAGE1_FAILURE_REASON
        )
        public_message = (
            _STAGE1_DEADLINE_MESSAGE
            if deadline_exceeded
            else _STAGE1_FAILURE_MESSAGE
        )
        # Move the session to the terminal STAGE1_FAILED state. Without this
        # the session was left in PROCESSING_STAGE1 forever — a provider parse
        # error / rate-limit / timeout stranded it as perpetually "processing"
        # with no recovery once the iOS app's in-memory recording was gone.
        # Mirrors the empty-transcript path's transition to its own terminal
        # failed state.
        await _raise_stage1_failure(
            db,
            session,
            reason=reason,
            public_message=public_message,
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

    # Populate the recovery handoff before commit starts. If cancellation lands
    # after PostgreSQL accepts the commit but before the await returns, the
    # owner can re-read AWAITING_REVIEW and continue the success path safely.
    progress.transcript = transcript
    progress.note = stage1_note
    progress.latency_ms = stage1_latency_ms

    # The DB commit is the terminal success ownership decision. The outer
    # wrapper performs external audit, notification, and cleanup post-commit.
    await db.commit()


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
    # Same template-aware classification as run_stage1 — an appended
    # recording must flag triggers by the session's own template, or the
    # follow-up segments would silently get weaker visual coverage than the
    # original ones in the very same transcript.
    merged = await classify_triggers(
        merged, template=await _resolve_trigger_template(db, session)
    )
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

    pinned_key, pinned_custom_id = stored_template_pin(session)
    try:
        note = await generate_stage1_note(
            transcript=merged,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
            output_language=session.output_language,
            template_key=pinned_key,
            custom_template_id=pinned_custom_id,
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
