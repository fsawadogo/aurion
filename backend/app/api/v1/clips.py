"""Clips API — receive masked video clips from iOS.

POST /api/v1/clips/{session_id} — single masked H.264 clip (no audio
track, audio is stripped iOS-side per the dual-mode plan), persisted to
S3 at ``clips/{session_id}/{clip_id}.mp4`` with KMS server-side
encryption. iOS uploads after stop, before transcription, alongside any
JPEG frames the session captured under the existing frames endpoint.

This is the clip-path sibling to ``/api/v1/frames/{session_id}``. The
auth, owner assertion, fail-closed masking gate, KMS-encrypted S3 write,
audit emission, and response shape mirror that endpoint exactly — the
shared validation surface lives in `_helpers.py` so the DRY contract
holds (§6c).

Per CLAUDE.md: "Raw video frames never leave iOS unmasked — masking
status logged before any upload." The clip path enforces the same gate
via the boolean `masking_confirmed` flag; iOS's `MaskingPipeline.maskClip`
fail-closes any clip where a per-frame face-detect fails, so a `True`
flag reaching this endpoint is the equivalent of the frame path's
four-field MaskingProof shaped down to a single boolean (the per-clip
frame counts ride on `ClipMaskingMetadata` for the audit row).
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import (
    assert_masking_confirmed,
    get_owned_session_or_404,
    parse_clip_masking_metadata,
    write_audit,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.modules.auth.service import CurrentUser, get_current_user

logger = logging.getLogger("aurion.api.clips")

router = APIRouter(prefix="/clips", tags=["clips"])

# iOS strips the audio track before upload — the multipart body is a
# video-only H.264 MP4. Anything else fails fast at the boundary.
_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"video/mp4"})

# How many characters of the session_id appear in log lines. Matches
# `_session_prefix` truncation pattern from peer services so logs are
# greppable without leaking the full UUID (PHI-adjacent identifier).
_SESSION_LOG_PREFIX_LEN = 8


def _session_log_prefix(session_id: uuid.UUID) -> str:
    return str(session_id)[:_SESSION_LOG_PREFIX_LEN]


class ClipUploadResponse(BaseModel):
    """Response shape after a successful clip upload.

    Mirrors `FrameUploadResponse` plus the clip-specific fields the iOS
    reviewer needs to render the inline player chip: `clip_id`,
    `duration_ms`, and `evidence_kind` (always `"clip"` for this
    endpoint; included so a polymorphic client can branch on it without
    inspecting URL path).
    """

    session_id: str
    clip_id: str
    s3_key: str
    bytes_uploaded: int
    duration_ms: int
    evidence_kind: str = "clip"


@router.post("/{session_id}", response_model=ClipUploadResponse)
async def upload_clip(
    session_id: uuid.UUID,
    timestamp_ms: int = Form(..., ge=0),
    duration_ms: int = Form(..., ge=1),
    trigger_segment_id: str = Form(..., min_length=1),
    frames_total: int = Form(..., ge=1),
    frames_with_faces: int = Form(..., ge=0),
    masking_confirmed: bool = Form(...),
    # #324 clip cadence floor — how this clip was produced on iOS.
    # "trigger" = extracted at a spoken-keyword trigger timestamp (today's
    # behavior); "cadence" = extracted by the during-recording cadence
    # timer to fill a silent gap. Defaults to "trigger" so existing iOS
    # builds (which don't send the field) keep the prior semantics. Not
    # PHI — a two-value provenance enum, carried into the audit + log for
    # count-only telemetry.
    source: Literal["trigger", "cadence"] = Form("trigger"),
    clip: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClipUploadResponse:
    """Persist a single masked H.264 clip to S3 for Stage 2 enrichment.

    Order of operations matches `upload_frame`:

    1. Auth (handled by `get_current_user` dependency).
    2. Owner assertion: a CLINICIAN can only post to their own sessions.
    3. **Fail-closed masking gate (P0-01)**: reject before any S3 write
       if `masking_confirmed` is False.
    4. Content-type validation: only `video/mp4` is accepted.
    5. KMS-encrypted S3 PutObject under `clips/{session_id}/{clip_id}.mp4`.
       The bucket-level default encryption already enforces KMS; we
       pass `ServerSideEncryption="aws:kms"` for defense-in-depth and
       to match frames.py.
    6. Emit `CLIP_UPLOADED` audit event carrying the masking metadata.
    7. Return `ClipUploadResponse`.
    """
    # 1+2. Owner assertion (this is /clips/ not /me/clips/, mirrors
    # frames.py: clinician routes use `get_owned_session_or_404` which
    # surfaces 404 on cross-clinician access for CLINICIAN role and 403
    # for other non-bypass roles — see `_helpers.assert_owner`).
    await get_owned_session_or_404(db, session_id, user)

    # 3. Fail-closed gate — BEFORE any S3 work.
    assert_masking_confirmed(masking_confirmed)

    # Validate the per-clip masking metadata (faces_blurred defaults to
    # frames_with_faces; the maskClip path fail-closes on partial blur
    # so any clip reaching this endpoint has blurred every detected face).
    masking_metadata = parse_clip_masking_metadata(
        frames_total=frames_total,
        frames_with_faces=frames_with_faces,
    )

    # 4. Content-type validation. Empty/None content_type is treated as
    # invalid — we want an explicit `video/mp4` declaration.
    if clip.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported clip content type: {clip.content_type!r}. "
                f"Expected one of: {sorted(_ALLOWED_CONTENT_TYPES)}."
            ),
        )

    body = await clip.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty clip body")

    # 5. KMS-encrypted S3 PutObject. The clip_id is server-generated so
    # the iOS side never picks the key; this also prevents two clips
    # with the same trigger_segment_id from clobbering each other when
    # the eval team replays a session.
    #
    # #324: embed the trigger-anchor timestamp_ms in the key prefix
    # (zero-padded to 9 digits for lexical sort) so Stage 2 can recover
    # each clip's real timestamp from the key alone. Before this, the key
    # carried no timestamp, so the vision service mis-anchored every clip
    # to trigger_segments[0]; with the prefix it anchors each clip to its
    # nearest transcript segment. Pattern: clips/{sid}/{ts:09d}_{clip_id}.mp4.
    clip_id = uuid.uuid4().hex
    key = f"clips/{session_id}/{timestamp_ms:09d}_{clip_id}.mp4"
    try:
        s3 = get_s3_client()
        s3.put_object(
            Bucket=FRAMES_BUCKET,
            Key=key,
            Body=body,
            ContentType="video/mp4",
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        # Log session prefix + key prefix only — no full UUID, no body.
        logger.error(
            "Clip upload failed: session=%s key=%s error=%s",
            _session_log_prefix(session_id), key[:32], exc,
        )
        raise HTTPException(status_code=500, detail=f"Clip upload failed: {exc}")

    # 6. Audit event. Whitelisted kwargs per `ALLOWED_AUDIT_KWARGS` —
    # see `core/audit_events.py:CLIP_UPLOADED`.
    await write_audit(
        session_id,
        AuditEventType.CLIP_UPLOADED,
        timestamp_ms=timestamp_ms,
        bytes=len(body),
        duration_ms=duration_ms,
        trigger_segment_id=trigger_segment_id,
        masking_status="success",
        frames_total=masking_metadata.frames_total,
        frames_with_faces=masking_metadata.frames_with_faces,
        faces_blurred=masking_metadata.faces_blurred,
        source=source,
    )

    logger.info(
        "Clip uploaded: session=%s clip=%s bytes=%d duration_ms=%d source=%s",
        _session_log_prefix(session_id), clip_id[:8], len(body), duration_ms,
        source,
    )

    return ClipUploadResponse(
        session_id=str(session_id),
        clip_id=clip_id,
        s3_key=key,
        bytes_uploaded=len(body),
        duration_ms=duration_ms,
    )
