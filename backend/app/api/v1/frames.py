"""Frames API — receive masked video/screen frames from iOS.

POST /api/v1/frames/{session_id} — single masked frame, persisted to S3 at
``frames/{session_id}/{timestamp_ms}.jpg``. iOS uploads after stop, before
transcription. The Stage 2 vision pipeline reads from this exact key
pattern to anchor frames against transcript trigger segments.

Per CLAUDE.md: "Raw video frames never leave iOS unmasked — masking status
logged before any upload." The endpoint enforces this by REQUIRING a
masking proof on every upload (P0-02). Any request missing the proof
fields, or asserting a non-success masking status, is rejected before the
bytes touch S3.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import (
    get_owned_session_or_404,
    parse_masking_proof,
    write_audit,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.modules.auth.service import CurrentUser, get_current_user

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
    frame_type: str = Form(..., description="'video' or 'screen'"),
    masking_status: str = Form(..., description="Must be 'success'"),
    faces_detected: int = Form(..., ge=0),
    phi_regions_redacted: int = Form(..., ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist a single masked frame to S3 for later Stage 2 enrichment.

    P0-02: rejects uploads without a verifiable masking proof. The proof
    fields are recorded on the `frame_uploaded` audit event so the PHI
    masking report can prove 100% on-device masking before transmission.
    """
    proof = parse_masking_proof(
        frame_type=frame_type,
        masking_status=masking_status,
        faces_detected=faces_detected,
        phi_regions_redacted=phi_regions_redacted,
    )
    await get_owned_session_or_404(db, session_id, user)

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

    await write_audit(
        session_id,
        AuditEventType.FRAME_UPLOADED,
        timestamp_ms=timestamp_ms,
        bytes=len(body),
        frame_type=proof.frame_type,
        masking_status=proof.masking_status,
        faces_detected=proof.faces_detected,
        phi_regions_redacted=proof.phi_regions_redacted,
    )

    return FrameUploadResponse(
        session_id=str(session_id),
        s3_key=key,
        bytes_uploaded=len(body),
    )
