"""Frames API — receive masked video/screen frames from iOS.

POST /api/v1/frames/{session_id} — single masked frame, persisted to S3 at
``frames/{session_id}/{timestamp_ms}.jpg``. iOS uploads after stop, before
transcription. The Stage 2 vision pipeline reads from this exact key
pattern to anchor frames against transcript trigger segments.

Per CLAUDE.md: "Raw video frames never leave iOS unmasked — masking status
logged before any upload." iOS confirms masking via the AuditLogger before
calling this endpoint, so we trust the iOS-side audit trail and write the
frame to the masked-frames bucket.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.session.service import get_session

logger = logging.getLogger("aurion.api.frames")

router = APIRouter(prefix="/frames", tags=["frames"])


class FrameUploadResponse(BaseModel):
    session_id: str
    s3_key: str
    bytes_uploaded: int


@router.post("/{session_id}", response_model=FrameUploadResponse)
async def upload_frame(
    session_id: uuid.UUID,
    timestamp_ms: int = Form(...),
    frame_file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist a single masked frame to S3 for later Stage 2 enrichment."""
    session = await get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await frame_file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty frame body")

    key = f"frames/{session_id}/{timestamp_ms}.jpg"
    try:
        s3 = get_s3_client()
        s3.put_object(
            Bucket=FRAMES_BUCKET,
            Key=key,
            Body=body,
            ContentType="image/jpeg",
        )
    except Exception as exc:
        logger.error(
            "Frame upload failed: session=%s key=%s error=%s",
            session_id, key, exc,
        )
        raise HTTPException(status_code=500, detail=f"Frame upload failed: {exc}")

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(session_id),
        event_type="frame_uploaded",
        timestamp_ms=timestamp_ms,
        bytes=len(body),
    )

    return FrameUploadResponse(
        session_id=str(session_id),
        s3_key=key,
        bytes_uploaded=len(body),
    )
