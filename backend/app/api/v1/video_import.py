"""Web-portal encounter-video import routes + orchestrator (VID-02).

Clinician-facing ``/api/v1/me/video-imports`` surface for uploading a
recorded encounter video and running it through the SAME backend AI pipeline
iOS uses. Audio spine only in this slice (frames + server-side masking land
in VID-03/04).

Every route is gated by ``feature_flags.video_import_enabled`` (404 when off),
so the whole surface ships dark. The background orchestrator
(``_run_video_import_in_background``) mirrors ``notes.py``'s Stage 2 detached
task: it owns its own DB session, moves the job row pending → running →
completed/failed, and the raw uploaded video is purged immediately after
audio extraction (the only unmasked-PHI artifact in the flow).
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, write_audit
from app.api.v1.transcription import run_stage1
from app.core.audit_events import AuditEventType
from app.core.database import async_session_factory, get_db
from app.core.s3 import (
    VIDEO_IMPORTS_BUCKET,
    generate_presigned_evidence_url,
    get_s3_client,
)
from app.core.types import SessionState
from app.modules.alerts.service import AlertSeverity, try_publish_alert
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.cleanup.service import purge_raw_video
from app.modules.config.appconfig_client import get_config
from app.modules.session.service import (
    confirm_consent,
    create_session,
    get_audit_event_for_state,
    get_session,
    transition_session,
)
from app.modules.video_import import jobs
from app.modules.video_import.extraction import extract_audio

logger = logging.getLogger("aurion.api.video_import")

router = APIRouter(prefix="/me/video-imports", tags=["video-import"])

# Presigned PUT validity — long enough for a clinician to upload a large
# encounter video over a clinic connection, short enough that a leaked URL
# expires quickly. The web slice (VID-05) swaps this single-PUT presign for
# S3 multipart; the single PUT is sufficient for the backend + tests now.
_UPLOAD_URL_TTL_SECONDS = 3600


def _require_enabled() -> None:
    """404 the entire surface unless the master flag is on (ships dark)."""
    if not get_config().feature_flags.video_import_enabled:
        raise HTTPException(status_code=404, detail="Not found")


# ── Request / response models ─────────────────────────────────────────────


class CreateVideoImportRequest(BaseModel):
    specialty: str
    consultation_type: Optional[str] = None
    encounter_context: Optional[str] = None
    output_language: str = "en"
    encounter_type: str = "doctor_patient"
    capture_mode: str = "multimodal"
    # The clinician attests patient consent was obtained at the ORIGINAL
    # recording (the import substitute for the bypassed live consent gate).
    # Must be True or the create is rejected — the consent hard-block is
    # preserved, just evidenced differently (CONSENT_ATTESTED audit).
    consent_attested: bool = False
    consent_method: str = "attested"


class CreateVideoImportResponse(BaseModel):
    session_id: str
    job_id: str
    upload_url: str
    s3_key: str


class VideoImportStatusResponse(BaseModel):
    session_id: str
    job_id: str
    status: str
    session_state: str
    frames_extracted: int
    frames_masked: int
    frames_dropped: int
    raw_video_purged: bool
    new_note_version: Optional[int] = None
    error_message: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────


@router.post("", response_model=CreateVideoImportResponse)
async def create_video_import(
    body: CreateVideoImportRequest,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an import session + return a presigned PUT URL for the video.

    The session is created in CONSENT_PENDING with ``import_source`` set; the
    consent attestation immediately confirms consent (CONSENT_ATTESTED), so
    the orchestrator may later drive RECORDING → PROCESSING_STAGE1 through the
    normal consent hard-gate. The raw video is uploaded by the client
    straight to S3 via the returned presigned PUT (the backend never streams
    the bytes).
    """
    if not body.consent_attested:
        raise HTTPException(
            status_code=400,
            detail="consent_attested must be true — consent is a hard gate.",
        )

    session = await create_session(
        db,
        clinician_id=user.user_id,
        specialty=body.specialty,
        consultation_type=body.consultation_type,
        encounter_context=body.encounter_context,
        output_language=body.output_language,
        encounter_type=body.encounter_type,
        capture_mode=body.capture_mode,
    )
    session.import_source = "video_upload"
    await db.flush()

    await confirm_consent(db, session)
    await write_audit(
        session.id,
        AuditEventType.CONSENT_ATTESTED,
        actor_id=str(user.user_id),
        method=body.consent_method,
    )

    s3_key = f"video-imports/{session.id}/{uuid.uuid4()}.mp4"
    job = await jobs.create_job(db, session.id, raw_video_s3_key=s3_key)

    upload_url = generate_presigned_evidence_url(
        s3_key,
        ttl_seconds=_UPLOAD_URL_TTL_SECONDS,
        bucket=VIDEO_IMPORTS_BUCKET,
        client_method="put_object",
    )

    return CreateVideoImportResponse(
        session_id=str(session.id),
        job_id=str(job.id),
        upload_url=upload_url,
        s3_key=s3_key,
    )


@router.post("/{session_id}/process", response_model=VideoImportStatusResponse)
async def process_video_import(
    session_id: uuid.UUID,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kick off processing once the client has uploaded the video to S3.

    Fail-closed: the raw video object must already exist (HEAD it) and the
    session must still be in CONSENT_PENDING with consent confirmed.
    """
    session = await get_owned_session_or_404(db, session_id, user)
    if session.state != SessionState.CONSENT_PENDING or not session.consent_confirmed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Import not in a processable state "
                f"(state={session.state.value}, consent={session.consent_confirmed})."
            ),
        )

    job = await jobs.get_job_for_session(db, session_id)
    if job is None or not job.raw_video_s3_key:
        raise HTTPException(status_code=404, detail="No import job for session.")
    if job.status not in ("pending", "failed"):
        raise HTTPException(
            status_code=409, detail=f"Job already {job.status}."
        )

    # Fail-closed: do not start processing for a video that was never uploaded.
    client = get_s3_client()
    try:
        client.head_object(Bucket=VIDEO_IMPORTS_BUCKET, Key=job.raw_video_s3_key)
    except (BotoCoreError, ClientError):
        raise HTTPException(
            status_code=409,
            detail="Uploaded video not found — upload before processing.",
        )

    await write_audit(
        session_id,
        AuditEventType.VIDEO_IMPORT_STARTED,
        actor_id=str(user.user_id),
    )
    asyncio.create_task(_run_video_import_in_background(session_id, job.id))

    return _status_response(session, job)


@router.get("/{session_id}/status", response_model=VideoImportStatusResponse)
async def get_video_import_status(
    session_id: uuid.UUID,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the import job + session state for the progress UI."""
    session = await get_owned_session_or_404(db, session_id, user)
    job = await jobs.get_job_for_session(db, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No import job for session.")
    return _status_response(session, job)


def _status_response(session, job) -> VideoImportStatusResponse:
    return VideoImportStatusResponse(
        session_id=str(session.id),
        job_id=str(job.id),
        status=job.status,
        session_state=session.state.value,
        frames_extracted=job.frames_extracted,
        frames_masked=job.frames_masked,
        frames_dropped=job.frames_dropped,
        raw_video_purged=job.raw_video_purged_at is not None,
        new_note_version=job.new_note_version,
        error_message=job.error_message,
    )


# ── Background orchestrator ───────────────────────────────────────────────


async def _run_video_import_in_background(
    session_id: uuid.UUID, job_id: uuid.UUID
) -> None:
    """Detached task: extract audio → Stage 1 → purge raw video.

    Owns its own DB session (the request that scheduled it has returned).
    Mirrors ``notes.py::_run_stage2_in_background``'s error contract: failures
    are recorded on the job row + a ``VIDEO_IMPORT_FAILED`` audit event +
    CRITICAL alert, and never bubble. The raw uploaded video is purged
    immediately after extraction (and best-effort on failure) so no unmasked
    video lingers past processing.
    """
    async with async_session_factory() as db:
        job = await jobs.get_job(db, job_id)
        session = await get_session(db, session_id)
        if job is None or session is None:
            logger.error(
                "Video-import job/session missing: job=%s session=%s",
                job_id,
                session_id,
            )
            return

        raw_key = job.raw_video_s3_key
        try:
            await jobs.mark_running(db, job)

            # 1. Download raw video to task-local scratch + extract audio.
            with tempfile.TemporaryDirectory() as tmp:
                video_path = os.path.join(tmp, "in.mp4")
                wav_path = os.path.join(tmp, "audio.wav")
                client = get_s3_client()
                client.download_file(VIDEO_IMPORTS_BUCKET, raw_key, video_path)
                await extract_audio(video_path, wav_path)
                with open(wav_path, "rb") as fh:
                    audio_bytes = fh.read()

            # 2. Purge the raw video immediately (fail-closed: a purge failure
            #    aborts the job rather than leaving unmasked video in S3).
            await purge_raw_video(str(session_id), raw_key)
            await jobs.mark_raw_video_purged(db, job)

            # 3. Drive the state machine through the normal consent hard-gate:
            #    CONSENT_PENDING(consent_confirmed) → RECORDING → PROCESSING_STAGE1.
            await transition_session(db, session, SessionState.RECORDING)
            await write_audit(
                session_id, get_audit_event_for_state(SessionState.RECORDING)
            )
            await transition_session(db, session, SessionState.PROCESSING_STAGE1)
            await write_audit(session_id, AuditEventType.STAGE1_STARTED)

            # 4. Shared Stage 1 pipeline → AWAITING_REVIEW + note delivered.
            await run_stage1(db, session, audio_bytes)

            await jobs.mark_completed(db, job)
            await write_audit(
                session_id,
                AuditEventType.VIDEO_IMPORT_COMPLETE,
                frames_extracted=0,
                frames_masked=0,
                frames_dropped=0,
            )
        except Exception as exc:  # noqa: BLE001 — deliberately catch all
            logger.exception(
                "Video import failed: session=%s job=%s", session_id, job_id
            )
            reason = str(exc)[:200]
            # Best-effort: never leave an unmasked raw video behind on failure.
            if job.raw_video_purged_at is None and raw_key:
                try:
                    await purge_raw_video(str(session_id), raw_key)
                    await jobs.mark_raw_video_purged(db, job)
                except Exception:
                    logger.exception(
                        "Failed to purge raw video after import failure: session=%s",
                        session_id,
                    )
            try:
                await jobs.mark_failed(db, job, reason)
            except Exception:
                logger.exception("Failed to mark import job failed: %s", job_id)
            await write_audit(
                session_id, AuditEventType.VIDEO_IMPORT_FAILED, reason=reason
            )
            await try_publish_alert(
                alert_type=AuditEventType.VIDEO_IMPORT_FAILED.value,
                severity=AlertSeverity.CRITICAL,
                source="video_import_job",
                message="Video import job failed",
                metadata={"session_id": str(session_id), "reason": reason},
            )
