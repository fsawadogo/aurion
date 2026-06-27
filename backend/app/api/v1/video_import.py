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
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, write_audit
from app.api.v1.transcription import run_stage1
from app.core.audit_events import AuditEventType
from app.core.database import async_session_factory, get_db
from app.core.models import TranscriptModel
from app.core.s3 import (
    FRAMES_BUCKET,
    VIDEO_IMPORTS_BUCKET,
    generate_presigned_evidence_url,
    get_s3_client,
)
from app.core.types import MaskingProof, SessionState, Transcript
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
from app.modules.video_import.extraction import extract_audio, extract_frames_at_windows
from app.modules.video_import.masking import mask_frame
from app.modules.vision.service import get_frame_window_ms

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
    # Optional custom template (tpl-03) to apply to the imported note — its
    # section structure + any AI instructions it carries. Validated as owned by
    # the clinician; None = the specialty default.
    custom_template_id: Optional[str] = None
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


# ── Multipart upload (VID-11) ─────────────────────────────────────────────
# For large videos (>~ a few hundred MB) a single presigned PUT is fragile —
# no resume, dies on a flaky connection near the end. These endpoints back a
# browser-driven S3 multipart upload (one presigned URL per part) against the
# SAME job s3_key the single-PUT path uses; the small-file path stays the
# default. Part size is server-chosen so the client just slices to it.

_MULTIPART_PART_SIZE = 32 * 1024 * 1024  # 32 MB
_S3_MAX_PARTS = 10000  # S3 hard limit


class StartMultipartRequest(BaseModel):
    size_bytes: int = Field(..., gt=0)


class MultipartPart(BaseModel):
    part_number: int
    url: str


class StartMultipartResponse(BaseModel):
    upload_id: str
    key: str
    part_size: int
    parts: list[MultipartPart]


class CompletedPart(BaseModel):
    part_number: int
    etag: str


class CompleteMultipartRequest(BaseModel):
    upload_id: str
    parts: list[CompletedPart]


class AbortMultipartRequest(BaseModel):
    upload_id: str


# ── Routes ────────────────────────────────────────────────────────────────


async def create_import_session(
    db: AsyncSession,
    *,
    clinician_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: CreateVideoImportRequest,
    auto_advance_stage2: bool = False,
) -> CreateVideoImportResponse:
    """Shared create logic for the clinician + admin video-import surfaces.

    Creates the import session (owned by ``clinician_id``), records the
    consent attestation (audited under ``actor_id``), opens the job, and
    presigns the upload PUT. ``auto_advance_stage2`` is stamped on the job so
    the orchestrator runs Stage 2 automatically (admin/eval bulk runs).

    The caller validates the consent attestation before calling this (the
    hard gate) so the rejection message stays at the HTTP boundary.
    """
    resolved_custom_template_id: Optional[uuid.UUID] = None
    if body.custom_template_id:
        # tpl-03: apply a clinician-owned custom template (carries structure +
        # AI instructions). Ownership-scoped lookup; reject an unknown/foreign
        # id rather than silently falling back, since the upload UI only lists
        # owned templates (a miss means a stale pick or tampering).
        from app.modules.custom_templates.service import get_owned_or_shared

        try:
            ref = uuid.UUID(body.custom_template_id)
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status_code=404, detail="Custom template not found")
        owned = await get_owned_or_shared(ref, clinician_id, db)
        if owned is None:
            raise HTTPException(status_code=404, detail="Custom template not found")
        resolved_custom_template_id = owned.id

    session = await create_session(
        db,
        clinician_id=clinician_id,
        specialty=body.specialty,
        consultation_type=body.consultation_type,
        encounter_context=body.encounter_context,
        output_language=body.output_language,
        encounter_type=body.encounter_type,
        capture_mode=body.capture_mode,
        custom_template_id=resolved_custom_template_id,
    )
    session.import_source = "video_upload"
    await db.flush()

    await confirm_consent(db, session)
    await write_audit(
        session.id,
        AuditEventType.CONSENT_ATTESTED,
        actor_id=str(actor_id),
        method=body.consent_method,
    )

    s3_key = f"video-imports/{session.id}/{uuid.uuid4()}.mp4"
    job = await jobs.create_job(
        db, session.id, raw_video_s3_key=s3_key,
        auto_advance_stage2=auto_advance_stage2,
    )

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


@router.post("", response_model=CreateVideoImportResponse)
async def create_video_import(
    body: CreateVideoImportRequest,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a clinician import session + return a presigned PUT URL.

    The session is created in CONSENT_PENDING with ``import_source`` set; the
    consent attestation immediately confirms consent (CONSENT_ATTESTED), so
    the orchestrator may later drive RECORDING → PROCESSING_STAGE1 through the
    normal consent hard-gate. Clinician imports stop at AWAITING_REVIEW for
    human review (no auto-advance).
    """
    if not body.consent_attested:
        raise HTTPException(
            status_code=400,
            detail="consent_attested must be true — consent is a hard gate.",
        )
    return await create_import_session(
        db,
        clinician_id=user.user_id,
        actor_id=user.user_id,
        body=body,
        auto_advance_stage2=False,
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
    return await start_processing(db, session, actor_id=user.user_id)


async def start_processing(
    db: AsyncSession, session, *, actor_id: uuid.UUID
) -> VideoImportStatusResponse:
    """Shared processing kickoff (clinician + admin surfaces).

    Fail-closed: the session must be CONSENT_PENDING with consent confirmed,
    a pending/failed job must exist, and the raw video object must already be
    in S3 (HEAD it). Dispatches the background orchestrator.
    """
    if session.state != SessionState.CONSENT_PENDING or not session.consent_confirmed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Import not in a processable state "
                f"(state={session.state.value}, consent={session.consent_confirmed})."
            ),
        )

    job = await jobs.get_job_for_session(db, session.id)
    if job is None or not job.raw_video_s3_key:
        raise HTTPException(status_code=404, detail="No import job for session.")
    if job.status not in ("pending", "failed"):
        raise HTTPException(status_code=409, detail=f"Job already {job.status}.")

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
        session.id,
        AuditEventType.VIDEO_IMPORT_STARTED,
        actor_id=str(actor_id),
    )
    asyncio.create_task(_run_video_import_in_background(session.id, job.id))
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


async def _job_key_or_404(db: AsyncSession, session_id: uuid.UUID) -> tuple:
    """Return ``(job, raw_video_s3_key)`` for an owned session or raise 404."""
    job = await jobs.get_job_for_session(db, session_id)
    if job is None or not job.raw_video_s3_key:
        raise HTTPException(status_code=404, detail="No import job for session.")
    return job, job.raw_video_s3_key


def _presign_part(s3_key: str, upload_id: str, part_number: int) -> str:
    return get_s3_client().generate_presigned_url(
        ClientMethod="upload_part",
        Params={
            "Bucket": VIDEO_IMPORTS_BUCKET,
            "Key": s3_key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=_UPLOAD_URL_TTL_SECONDS,
    )


def start_multipart(s3_key: str, size_bytes: int) -> StartMultipartResponse:
    """Open an S3 multipart upload for ``s3_key`` and presign every part."""
    num_parts = max(1, -(-size_bytes // _MULTIPART_PART_SIZE))  # ceil-div
    if num_parts > _S3_MAX_PARTS:
        raise HTTPException(status_code=400, detail="File too large for upload.")
    client = get_s3_client()
    created = client.create_multipart_upload(
        Bucket=VIDEO_IMPORTS_BUCKET, Key=s3_key, ContentType="video/mp4"
    )
    upload_id = created["UploadId"]
    parts = [
        MultipartPart(part_number=n, url=_presign_part(s3_key, upload_id, n))
        for n in range(1, num_parts + 1)
    ]
    return StartMultipartResponse(
        upload_id=upload_id, key=s3_key, part_size=_MULTIPART_PART_SIZE, parts=parts
    )


@router.post("/{session_id}/multipart/start", response_model=StartMultipartResponse)
async def start_multipart_upload(
    session_id: uuid.UUID,
    body: StartMultipartRequest,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Open a multipart upload for a large video + return presigned part URLs."""
    await get_owned_session_or_404(db, session_id, user)
    _, s3_key = await _job_key_or_404(db, session_id)
    return start_multipart(s3_key, body.size_bytes)


@router.post(
    "/{session_id}/multipart/{part_number}/presign", response_model=MultipartPart
)
async def presign_multipart_part(
    session_id: uuid.UUID,
    part_number: int,
    body: AbortMultipartRequest,  # carries upload_id
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-mint a presigned URL for one part (e.g. after the original expired)."""
    await get_owned_session_or_404(db, session_id, user)
    _, s3_key = await _job_key_or_404(db, session_id)
    return MultipartPart(
        part_number=part_number,
        url=_presign_part(s3_key, body.upload_id, part_number),
    )


@router.post("/{session_id}/multipart/complete")
async def complete_multipart_upload(
    session_id: uuid.UUID,
    body: CompleteMultipartRequest,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Finalize the S3 multipart upload. The client then calls /process."""
    await get_owned_session_or_404(db, session_id, user)
    _, s3_key = await _job_key_or_404(db, session_id)
    get_s3_client().complete_multipart_upload(
        Bucket=VIDEO_IMPORTS_BUCKET,
        Key=s3_key,
        UploadId=body.upload_id,
        MultipartUpload={
            "Parts": [
                {"ETag": p.etag, "PartNumber": p.part_number}
                for p in sorted(body.parts, key=lambda p: p.part_number)
            ]
        },
    )
    return {"status": "uploaded"}


@router.post("/{session_id}/multipart/abort")
async def abort_multipart_upload(
    session_id: uuid.UUID,
    body: AbortMultipartRequest,
    _: None = Depends(_require_enabled),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abort an in-progress multipart upload (cancel/cleanup)."""
    await get_owned_session_or_404(db, session_id, user)
    _, s3_key = await _job_key_or_404(db, session_id)
    get_s3_client().abort_multipart_upload(
        Bucket=VIDEO_IMPORTS_BUCKET, Key=s3_key, UploadId=body.upload_id
    )
    return {"status": "aborted"}


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


async def _extract_and_mask_frames(
    db: AsyncSession, session_id: uuid.UUID, video_path: str
) -> tuple[int, int, int]:
    """Extract frames at the transcript's trigger windows + mask each.

    Returns ``(frames_extracted, frames_masked, frames_dropped)``.

    VID-03: ``mask_frame`` is the stub that drops every frame, so nothing is
    written to S3 — the import degrades to frames-absent. VID-04 swaps in real
    OpenCV masking + the S3 store + ``SERVER_MASKING_APPLIED`` audit behind the
    same call site (the success branch below). With the pilot's empty trigger
    lists this is a no-op (zero trigger segments → zero frames).
    """
    row = (
        await db.execute(
            select(TranscriptModel).where(TranscriptModel.session_id == session_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return (0, 0, 0)
    try:
        transcript = Transcript.model_validate_json(row.transcript_json)
    except Exception:  # noqa: BLE001 — a corrupt transcript just skips frames
        logger.warning("Unparseable transcript for session=%s — no frames", session_id)
        return (0, 0, 0)

    triggers = [s for s in transcript.segments if s.is_visual_trigger]
    if not triggers:
        return (0, 0, 0)

    windows = [
        (
            s.start_ms - get_frame_window_ms(s.trigger_type),
            s.end_ms + get_frame_window_ms(s.trigger_type),
        )
        for s in triggers
    ]
    fps = get_config().pipeline.video_import_fps
    frames = await extract_frames_at_windows(video_path, windows, fps)

    drop_zero = get_config().feature_flags.video_import_drop_zero_face_frames
    s3 = get_s3_client()
    masked = 0
    dropped = 0
    for ts_ms, jpg_bytes in frames:
        result = mask_frame(jpg_bytes, drop_zero_face=drop_zero)
        if result.status == "success" and result.image_bytes is not None:
            # Server-issued masking proof — same contract the iOS frame path
            # validates (P0-02). Constructing it asserts the success invariant
            # before the masked frame is stored.
            MaskingProof(
                frame_type="video",
                masking_status="success",
                faces_detected=result.faces_detected,
                phi_regions_redacted=0,
            )
            # Store under the SAME key shape the vision pipeline already reads.
            s3.put_object(
                Bucket=FRAMES_BUCKET,
                Key=f"frames/{session_id}/{ts_ms}.jpg",
                Body=result.image_bytes,
                ContentType="image/jpeg",
            )
            await write_audit(
                session_id,
                AuditEventType.SERVER_MASKING_APPLIED,
                timestamp_ms=ts_ms,
                faces_detected=result.faces_detected,
                faces_blurred=result.faces_blurred,
            )
            masked += 1
        else:
            await write_audit(
                session_id,
                AuditEventType.SERVER_MASKING_FAILED,
                timestamp_ms=ts_ms,
                reason=result.reason or "unknown",
            )
            dropped += 1
    return (len(frames), masked, dropped)


async def _auto_advance_stage2(
    db: AsyncSession, session, session_id: uuid.UUID
) -> Optional[int]:
    """Approve Stage 1 + run Stage 2 vision inline (admin/eval bulk imports).

    Mirrors the approve-stage1 route's dispatch, but runs Stage 2 inline
    (this is already a background task) and leaves the session in
    PROCESSING_STAGE2 — final approval + CONFLICTS resolution stay human.
    Returns the resulting note version (or None).

    Records a ``stage2_jobs`` row exactly like the iOS background path
    (``notes.py::_run_stage2_in_background``). Without it the iOS Stage-2
    poll (``GET /notes/{id}/stage2-status``) returns ``no_job`` forever and
    the dashboard tile stays "Stage 2 queued" even though the full note is
    ready — the bug that left two Jun-2026 imports visibly stuck. The poll
    reading ``completed`` is what drops the tile and surfaces the full note
    for the human's final review.
    """
    # Lazy imports — avoid a circular import with the notes/vision routers.
    from app.api.v1.vision import run_stage2_vision
    from app.modules.note_gen.service import approve_note, get_latest_note
    from app.modules.vision.jobs import (
        create_job,
        mark_completed,
        mark_failed,
        mark_running,
    )

    approved = await approve_note(str(session_id), db)
    await transition_session(db, session, SessionState.PROCESSING_STAGE2)
    await write_audit(
        session_id,
        AuditEventType.STAGE1_APPROVED,
        version=approved.version,
        provider_used=approved.provider_used,
        completeness_score=approved.completeness_score,
    )

    job = await create_job(session_id, db)
    await write_audit(
        session_id, AuditEventType.STAGE2_STARTED, job_id=str(job.id)
    )
    try:
        await mark_running(job.id, db)
        result = await run_stage2_vision(session_id, db)
        latest = await get_latest_note(str(session_id), db)
        new_version = latest.version if latest is not None else 0
        await mark_completed(
            job.id,
            new_note_version=new_version,
            frames_processed=result.frames_processed,
            db=db,
        )
        return new_version
    except Exception as exc:  # noqa: BLE001 — record on the job, then bubble
        # Mark the Stage-2 job failed so the iOS poll surfaces the failure
        # (not a perpetual "queued"); the outer video-import handler still
        # records VIDEO_IMPORT_FAILED + the CRITICAL alert when this re-raises.
        await mark_failed(job.id, str(exc), db)
        await write_audit(
            session_id,
            AuditEventType.STAGE2_FAILED,
            job_id=str(job.id),
            reason=str(exc)[:200],
        )
        raise


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

            # The raw video stays on task-local disk through frame extraction
            # (which needs the transcript's trigger windows from run_stage1),
            # then the S3 copy is purged. The tmp dir is removed on block exit
            # regardless of outcome.
            with tempfile.TemporaryDirectory() as tmp:
                video_path = os.path.join(tmp, "in.mp4")
                wav_path = os.path.join(tmp, "audio.wav")
                client = get_s3_client()
                client.download_file(VIDEO_IMPORTS_BUCKET, raw_key, video_path)

                # 1. Extract audio → shared Stage 1 pipeline.
                await extract_audio(video_path, wav_path)
                with open(wav_path, "rb") as fh:
                    audio_bytes = fh.read()

                # Drive the state machine through the normal consent hard-gate:
                # CONSENT_PENDING(consent_confirmed) → RECORDING → PROCESSING_STAGE1.
                await transition_session(db, session, SessionState.RECORDING)
                await write_audit(
                    session_id, get_audit_event_for_state(SessionState.RECORDING)
                )
                await transition_session(db, session, SessionState.PROCESSING_STAGE1)
                await write_audit(session_id, AuditEventType.STAGE1_STARTED)

                await run_stage1(db, session, audio_bytes)  # → AWAITING_REVIEW
                # Persist the transcript + Stage 1 note + state transition now.
                # The orchestrator owns a manual session (async_session_factory
                # does NOT auto-commit — unlike the request-scoped get_db), so
                # without this the whole RDS transaction rolls back when the
                # task ends and the note is silently lost.
                await db.commit()

                # 2. Extract + mask frames at the transcript's trigger windows.
                #    VID-03: the masking stub drops every frame, so nothing is
                #    written to S3 (frames-absent). VID-04 swaps in real masking
                #    + S3 storage behind the same call.
                extracted, masked, dropped = await _extract_and_mask_frames(
                    db, session_id, video_path
                )

            # 3. Purge the raw video (fail-closed: a purge failure aborts the
            #    job rather than leaving unmasked video in S3).
            await purge_raw_video(str(session_id), raw_key)
            await jobs.mark_raw_video_purged(db, job)

            # 4. Admin/eval bulk runs auto-advance Stage 2 so the full
            #    multimodal note is produced without a manual Stage 1 approval.
            #    Clinician imports (auto_advance_stage2=False) stop at
            #    AWAITING_REVIEW for human review. Final approval +
            #    conflict resolution always stay human (the session is left in
            #    PROCESSING_STAGE2, never auto-approved to REVIEW_COMPLETE).
            new_version = None
            if job.auto_advance_stage2:
                new_version = await _auto_advance_stage2(db, session, session_id)

            await jobs.mark_completed(
                db,
                job,
                frames_extracted=extracted,
                frames_masked=masked,
                frames_dropped=dropped,
                new_note_version=new_version,
            )
            await write_audit(
                session_id,
                AuditEventType.VIDEO_IMPORT_COMPLETE,
                frames_extracted=extracted,
                frames_masked=masked,
                frames_dropped=dropped,
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
