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
from typing import Any, Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, write_audit
from app.api.v1.transcription import run_stage1
from app.core.audit_events import AuditEventType
from app.core.background import spawn_background_task
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
from app.modules.video_import.extraction import (
    concat_audio,
    extract_audio,
    extract_frames_at_windows,
    wav_duration_ms,
)
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
    # Multi-clip import: the number of sequential clips that make up this one
    # encounter. 1 = the classic single-clip import (response is byte-identical
    # to before). >1 requires feature_flags.multi_clip_import_enabled; the
    # response then carries an ordered `clips` list (one presigned PUT each),
    # uploaded in order and concatenated into one note. Capped to keep a single
    # encounter sane.
    clip_count: int = Field(default=1, ge=1, le=20)


class ClipUpload(BaseModel):
    """One clip's ordered slot + presigned PUT URL (multi-clip import)."""

    index: int
    s3_key: str
    upload_url: str


class CreateVideoImportResponse(BaseModel):
    session_id: str
    job_id: str
    # First clip's URL/key — kept for back-compat with the single-clip client.
    upload_url: str
    s3_key: str
    # Present (and length == clip_count) for a multi-clip import; None for a
    # single-clip import. Ordered; upload each clip to its slot in order.
    clips: Optional[list[ClipUpload]] = None


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

    def _presign(key: str) -> str:
        return generate_presigned_evidence_url(
            key,
            ttl_seconds=_UPLOAD_URL_TTL_SECONDS,
            bucket=VIDEO_IMPORTS_BUCKET,
            client_method="put_object",
        )

    # Multi-clip import (flag-gated): N ordinal-named clips, one presigned PUT
    # each, uploaded in order and concatenated into one note. Falls through to
    # the single-clip path (byte-identical to before) when clip_count == 1.
    multi_enabled = get_config().feature_flags.multi_clip_import_enabled
    if body.clip_count > 1 and not multi_enabled:
        raise HTTPException(status_code=400, detail="Multi-clip import is not enabled.")

    if body.clip_count > 1:
        keys = [
            f"video-imports/{session.id}/{i:02d}-{uuid.uuid4()}.mp4"
            for i in range(body.clip_count)
        ]
        clips = [
            ClipUpload(index=i, s3_key=k, upload_url=_presign(k))
            for i, k in enumerate(keys)
        ]
        job = await jobs.create_job(
            db, session.id, raw_video_s3_key=keys[0],
            raw_video_s3_keys=keys,
            auto_advance_stage2=auto_advance_stage2,
        )
        return CreateVideoImportResponse(
            session_id=str(session.id),
            job_id=str(job.id),
            upload_url=clips[0].upload_url,
            s3_key=keys[0],
            clips=clips,
        )

    s3_key = f"video-imports/{session.id}/{uuid.uuid4()}.mp4"
    job = await jobs.create_job(
        db, session.id, raw_video_s3_key=s3_key,
        auto_advance_stage2=auto_advance_stage2,
    )

    upload_url = _presign(s3_key)

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

    # Mark running synchronously at dispatch, BEFORE the detached task starts:
    # the job is `running` the moment /process returns, so a duplicate /process
    # is rejected (409 above) and a dropped/dead task stays recoverable by the
    # watchdog (#570) / startup sweep (#571) — both act only on `running` jobs.
    await jobs.mark_running(db, job)
    await write_audit(
        session.id,
        AuditEventType.VIDEO_IMPORT_STARTED,
        actor_id=str(actor_id),
    )
    # Retain a strong reference so the GC can't collect the task before it runs.
    # A bare ``asyncio.create_task`` is only weakly referenced by the loop and
    # can be garbage-collected mid-flight → the import never executes.
    spawn_background_task(
        _run_video_import_in_background(session.id, job.id), name="video-import"
    )
    return _status_response(session, job)


async def _reap_stale_job(db: AsyncSession, job, session_id: uuid.UUID) -> None:
    """Lazy watchdog shared by both status routes (clinician + admin).

    The orchestrator is a fire-and-forget ``asyncio.create_task`` — if its worker
    recycles or a step hangs, the task dies before its ``except → mark_failed``
    and the job is stranded ``running``, so the portal poll spins forever. On
    each poll, fail a job that's been running past the budget so the UI surfaces
    an error (and the job becomes re-runnable via ``/process``). Records
    ``VIDEO_IMPORT_FAILED`` to mirror the orchestrator's own failure path.
    """
    if await jobs.fail_if_stale(db, job):
        await write_audit(
            session_id,
            AuditEventType.VIDEO_IMPORT_FAILED,
            reason="watchdog: import exceeded the processing time budget",
        )


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
    await _reap_stale_job(db, job, session_id)
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


def _read_file_bytes(path: str) -> bytes:
    """Read a file fully into memory — run via ``asyncio.to_thread``.

    The extracted WAV can be tens of MB for a long encounter; a synchronous
    read would block the event loop for the read duration, so the caller
    offloads it to a worker thread (same rationale as the S3 download).
    """
    with open(path, "rb") as fh:
        return fh.read()


async def _download_to_path(client: Any, key: str, dest_path: str) -> None:
    """Download an S3 object to local disk OFF the event loop.

    boto3's ``download_file`` is synchronous; calling it directly on the API
    event loop blocks every concurrent request (e.g. the status poll) for the
    whole transfer — for a large encounter video that's seconds, long enough for
    the ALB to return a gateway 502 (no CORS headers → the browser mislabels it
    a CORS failure) and, under sustained load, for the container health check to
    fail and ECS to recycle the task. ``asyncio.to_thread`` keeps the loop
    responsive while the transfer runs in a worker thread.
    """
    await asyncio.to_thread(client.download_file, VIDEO_IMPORTS_BUCKET, key, dest_path)


def _mask_and_store_frame(
    s3: Any, session_id: uuid.UUID, ts_ms: int, jpg_bytes: bytes, drop_zero_face: bool
):
    """Mask one frame and, on success, store it to S3 — a single blocking unit.

    OpenCV masking is CPU-bound and ``s3.put_object`` is synchronous boto3; both
    run together in a worker thread (the caller wraps this in
    ``asyncio.to_thread``) so neither blocks the event loop. Returns the
    ``mask_frame`` result so the caller emits the (async) audit on the loop.
    Fail-closed is preserved: a non-success result skips the store entirely, so
    an unmasked frame is never written.
    """
    result = mask_frame(jpg_bytes, drop_zero_face=drop_zero_face)
    if result.status == "success" and result.image_bytes is not None:
        # Server-issued masking proof — asserts the success invariant before the
        # masked frame is stored (P0-02), same contract as the iOS frame path.
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
    return result


async def _extract_and_mask_frames(
    db: AsyncSession, session_id: uuid.UUID, clips: list[tuple[str, int]]
) -> tuple[int, int, int]:
    """Extract frames at the transcript's trigger windows + mask each.

    ``clips`` is the ordered ``[(video_path, start_offset_ms), ...]`` list. For
    a single-clip import it is ``[(path, 0)]`` and this behaves exactly as
    before. For a multi-clip import each trigger window (on the merged timeline)
    is routed to the clip that owns its start, extracted at the clip-local
    offset, and the stored frame keeps its MERGED timestamp so it still aligns
    with the transcript citations.

    Returns ``(frames_extracted, frames_masked, frames_dropped)``.

    VID-03: ``mask_frame`` is the stub that drops every frame, so nothing is
    written to S3 — the import degrades to frames-absent. VID-04 swaps in real
    OpenCV masking + the S3 store + ``SERVER_MASKING_APPLIED`` audit behind the
    same call site (the success branch below). With the pilot's empty trigger
    lists this is a no-op (zero trigger segments → zero frames).
    """
    if not clips:
        return (0, 0, 0)
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

    # Route each merged-timeline window to the clip that owns its start, then
    # extract per clip (clip-local windows) and re-offset to the merged ts.
    sorted_clips = sorted(clips, key=lambda c: c[1])
    per_clip: dict[int, list[tuple[int, int]]] = {}
    for start, end in windows:
        owner = 0
        for j, (_, off) in enumerate(sorted_clips):
            if off <= max(start, 0):
                owner = j
            else:
                break
        offset = sorted_clips[owner][1]
        per_clip.setdefault(owner, []).append(
            (max(start - offset, 0), max(end - offset, 0))
        )

    frames: list[tuple[int, bytes]] = []
    for owner, local_windows in per_clip.items():
        path, offset = sorted_clips[owner]
        local_frames = await extract_frames_at_windows(path, local_windows, fps)
        frames.extend((local_ts + offset, jpg) for local_ts, jpg in local_frames)

    drop_zero = get_config().feature_flags.video_import_drop_zero_face_frames
    s3 = get_s3_client()
    masked = 0
    dropped = 0
    for ts_ms, jpg_bytes in frames:
        # Mask + store off the event loop (OpenCV is CPU-bound, put_object is
        # sync boto3); the audit stays async on the loop.
        result = await asyncio.to_thread(
            _mask_and_store_frame, s3, session_id, ts_ms, jpg_bytes, drop_zero
        )
        if result.status == "success" and result.image_bytes is not None:
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
        # Ordered clip list — one entry for a single-clip import (legacy /
        # raw_video_s3_keys NULL), N for a multi-clip import. Concatenated in
        # THIS order into one audio timeline → one transcript → one note.
        clip_keys = [k for k in (job.raw_video_s3_keys or [raw_key]) if k]
        try:
            # The job was already marked ``running`` synchronously by
            # ``start_processing`` at dispatch (so a dropped task stays
            # watchdog-recoverable); the orchestrator just proceeds.
            # The raw clips stay on task-local disk through frame extraction
            # (which needs the transcript's trigger windows from run_stage1),
            # then the S3 copies are purged. The tmp dir is removed on block
            # exit regardless of outcome.
            with tempfile.TemporaryDirectory() as tmp:
                client = get_s3_client()

                # 1. Download + extract audio for every clip (in order), then
                #    concatenate into one continuous timeline. The read runs
                #    off the loop — the combined WAV can be tens of MB.
                wav_paths: list[str] = []
                # (video_path, start_offset_ms) per clip, for frame extraction
                # against the merged timeline.
                clips_with_offset: list[tuple[str, int]] = []
                cumulative_ms = 0
                for i, key in enumerate(clip_keys):
                    video_path = os.path.join(tmp, f"in_{i:02d}.mp4")
                    wav_path = os.path.join(tmp, f"audio_{i:02d}.wav")
                    await _download_to_path(client, key, video_path)
                    await extract_audio(video_path, wav_path)
                    wav_paths.append(wav_path)
                    clips_with_offset.append((video_path, cumulative_ms))
                    cumulative_ms += wav_duration_ms(wav_path)

                combined_wav = os.path.join(tmp, "combined.wav")
                merged = await concat_audio(wav_paths, combined_wav)
                audio_bytes = await asyncio.to_thread(_read_file_bytes, merged)

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

                # 2. Extract + mask frames at the transcript's trigger windows,
                #    mapping each window onto the clip that owns it by offset.
                #    VID-03: the masking stub drops every frame, so nothing is
                #    written to S3 (frames-absent). VID-04 swaps in real masking
                #    + S3 storage behind the same call.
                extracted, masked, dropped = await _extract_and_mask_frames(
                    db, session_id, clips_with_offset
                )

            # 3. Purge every raw clip (fail-closed: a purge failure aborts the
            #    job rather than leaving unmasked video in S3).
            for key in clip_keys:
                await purge_raw_video(str(session_id), key)
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
            # Best-effort: never leave an unmasked raw clip behind on failure —
            # purge EVERY clip of a multi-clip import.
            if job.raw_video_purged_at is None and clip_keys:
                try:
                    for key in clip_keys:
                        await purge_raw_video(str(session_id), key)
                    await jobs.mark_raw_video_purged(db, job)
                except Exception:
                    logger.exception(
                        "Failed to purge raw video(s) after import failure: session=%s",
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


async def recover_stuck_imports_on_startup() -> int:
    """Reap import jobs orphaned by a worker recycle — called once on startup.

    The orchestrator is a fire-and-forget ``asyncio.create_task``; a container
    recycle kills it before its in-process ``except → mark_failed`` runs, leaving
    the job stranded ``running`` (the portal shows "Extracting audio" forever).
    This owns its own DB session (the lifespan runs before requests are served),
    delegates the budget-gated job-state change to ``jobs.recover_orphaned_jobs``,
    and emits the matching ``VIDEO_IMPORT_FAILED`` audit per reaped session — the
    same event the orchestrator + per-poll watchdog write, so a stranded import
    never lacks an audit-log entry (CLAUDE.md). Best-effort: any failure here is
    logged and swallowed so recovery never blocks startup. Returns the count.
    """
    try:
        async with async_session_factory() as db:
            reaped = await jobs.recover_orphaned_jobs(db)
            for session_id in reaped:
                await write_audit(
                    session_id,
                    AuditEventType.VIDEO_IMPORT_FAILED,
                    reason="startup recovery: import did not complete before a worker restart",
                )
        if reaped:
            logger.warning(
                "Startup recovery failed %d orphaned video-import job(s)", len(reaped)
            )
        return len(reaped)
    except Exception:  # noqa: BLE001 — recovery must never block startup
        logger.exception("Video-import startup recovery failed")
        return 0
