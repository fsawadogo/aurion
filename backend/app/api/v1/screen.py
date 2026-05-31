"""Screen capture API — receive redacted screen frames from iOS and
merge OCR-extracted data into the session's latest note version.

POST /api/v1/screen/{session_id}
    iOS uploads each redacted screen frame here after stop. The backend
    runs `process_screen_frame` (PHI redaction → classification → OCR →
    extraction → routing), persists the lab values / imaging metadata
    as screen-sourced claims on a new note version, and returns the
    extraction result.

Per CLAUDE.md §"Phase 5 — Screen Capture Pipeline":
- lab_result → claims into the `investigations` section.
- imaging_viewer → metadata only into `imaging_review`.
- emr → audit-only, never injected.
- other → discarded.

Like the video frames endpoint (P0-02), every upload carries a masking
proof and the backend rejects anything claiming success-failed mismatch.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

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
from app.core.types import (
    NoteClaim,
    ScreenCaptureResult,
    ScreenLabValue,
)
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.note_gen.service import (
    create_note_version,
    get_latest_note,
)
from app.modules.screen.service import process_screen_frame

logger = logging.getLogger("aurion.api.screen")

router = APIRouter(prefix="/screen", tags=["screen"])


class ScreenUploadResponse(BaseModel):
    session_id: str
    frame_id: str
    screen_type: str
    integration_status: str
    note_section_target: Optional[str] = None
    claims_added: int = 0
    new_note_version: Optional[int] = None


@router.post("/{session_id}", response_model=ScreenUploadResponse)
async def upload_screen_frame(
    session_id: uuid.UUID,
    timestamp_ms: int = Form(...),
    frame_file: UploadFile = File(...),
    frame_type: str = Form(..., description="must be 'screen'"),
    masking_status: str = Form(..., description="must be 'success'"),
    faces_detected: int = Form(..., ge=0),
    phi_regions_redacted: int = Form(..., ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist + process a single screen frame, merging extracted data
    as new screen-sourced claims on the session's note.

    Failure modes are explicit:
    - Bad proof → 400.
    - Missing session → 404.
    - Empty body → 400.
    - OCR/processing exceptions bubble up as 500.
    """
    proof = parse_masking_proof(
        frame_type=frame_type,
        masking_status=masking_status,
        faces_detected=faces_detected,
        phi_regions_redacted=phi_regions_redacted,
    )

    if proof.frame_type != "screen":
        raise HTTPException(
            status_code=400,
            detail="POST /screen/{id} only accepts frame_type='screen'",
        )

    await get_owned_session_or_404(db, session_id, user)

    body = await frame_file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty frame body")

    # Persist the redacted bytes to S3 for compliance + later audit / eval.
    frame_id = f"screen_{timestamp_ms}"
    s3_key = f"screen_frames/{session_id}/{timestamp_ms}.jpg"
    try:
        get_s3_client().put_object(
            Bucket=FRAMES_BUCKET,
            Key=s3_key,
            Body=body,
            ContentType="image/jpeg",
        )
    except Exception as exc:
        logger.error("Screen frame upload failed: session=%s key=%s err=%s", session_id, s3_key, exc)
        raise HTTPException(status_code=500, detail=f"Screen frame upload failed: {exc}")

    result = await process_screen_frame(
        frame_id=frame_id,
        session_id=str(session_id),
        timestamp_ms=timestamp_ms,
        image_bytes=body,
    )

    if result is None:
        # Feature flag off — frame stored for audit, but no integration.
        return ScreenUploadResponse(
            session_id=str(session_id),
            frame_id=frame_id,
            screen_type="other",
            integration_status="discarded",
        )

    claims_added = 0
    new_version: Optional[int] = None
    if result.integration_status == "injected" and result.extracted_data is not None:
        claims_added, new_version = await _merge_screen_into_note(
            db=db,
            session_id=str(session_id),
            result=result,
        )

    await write_audit(
        session_id,
        AuditEventType.SCREEN_FRAME_PROCESSED,
        frame_id=frame_id,
        timestamp_ms=timestamp_ms,
        screen_type=result.screen_type,
        integration_status=result.integration_status,
        claims_added=claims_added,
        frame_type=proof.frame_type,
        masking_status=proof.masking_status,
        phi_regions_redacted=proof.phi_regions_redacted,
    )

    return ScreenUploadResponse(
        session_id=str(session_id),
        frame_id=frame_id,
        screen_type=result.screen_type,
        integration_status=result.integration_status,
        note_section_target=result.note_section_target,
        claims_added=claims_added,
        new_note_version=new_version,
    )


def _value_to_claim_text(screen_type: str, value: ScreenLabValue) -> str:
    """Render one extracted value as a descriptive-mode claim string.

    Strictly factual: name + value + unit. Never interprets or
    diagnoses — CLAUDE.md §"Descriptive Mode".
    """
    if screen_type == "imaging_viewer":
        return f"Imaging metadata captured: {value.name}: {value.value}".rstrip(": ")
    unit = f" {value.unit}" if value.unit else ""
    return f"Screen-captured {value.name}: {value.value}{unit}".strip()


async def _merge_screen_into_note(
    db: AsyncSession,
    session_id: str,
    result: ScreenCaptureResult,
) -> tuple[int, Optional[int]]:
    """Append screen-sourced claims to the target section of the latest
    note and write a new immutable version. Returns (claims_added,
    new_version) or (0, None) if there's no note yet or no values to
    merge.

    Note merge is intentionally append-only: existing claims are kept
    untouched so audit can show the screen capture as the source of the
    delta.
    """
    note = await get_latest_note(session_id, db)
    if note is None:
        logger.info(
            "Cannot merge screen data — no Stage 1 note yet for session=%s",
            session_id,
        )
        return 0, None

    target_section_id = result.note_section_target
    if target_section_id is None or result.extracted_data is None:
        return 0, None

    target_section = note.get_section(target_section_id)
    if target_section is None:
        logger.info(
            "Target section %s missing on note for session=%s — skipping merge",
            target_section_id, session_id,
        )
        return 0, None

    new_claims: list[NoteClaim] = []
    for idx, value in enumerate(result.extracted_data.values, start=1):
        new_claims.append(
            NoteClaim(
                id=f"sclaim_{result.frame_id}_{idx}",
                text=_value_to_claim_text(result.screen_type, value),
                source_type="screen",
                source_id=result.frame_id,
                source_quote=f"{value.name}: {value.value} {value.unit}".strip(),
            )
        )

    if not new_claims:
        return 0, None

    target_section.claims.extend(new_claims)
    # Stage 2 owns the `pending_video → populated` transition. Screen data
    # only promotes sections that were never captured at all.
    if target_section.status == "not_captured":
        target_section.status = "populated"

    version_record = await create_note_version(
        session_id=session_id,
        note=note,
        db=db,
    )
    return len(new_claims), version_record.version
