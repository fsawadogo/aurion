"""Admin / eval video-import routes (VID-06).

Same pipeline as the clinician `/me/video-imports` surface, but ADMIN +
EVAL_TEAM gated: lets the eval team process recorded test encounters,
optionally attributed to a specific clinician (``on_behalf_of_clinician_id``),
and auto-advancing Stage 2 by default so a full multimodal note is produced
without a manual Stage 1 approval.

Thin handlers — all the real work lives in the shared helpers in
``app/api/v1/video_import.py`` (DRY §6c).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404
from app.api.v1.video_import import (
    CreateVideoImportRequest,
    CreateVideoImportResponse,
    VideoImportStatusResponse,
    _reap_stale_job,
    _require_enabled,
    _status_response,
    create_import_session,
    start_processing,
)
from app.core.database import get_db
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.video_import import jobs

router = APIRouter(prefix="/admin/video-imports", tags=["admin", "video-import"])


class AdminCreateVideoImportRequest(CreateVideoImportRequest):
    # Attribute the import to a specific clinician (their My Notes inbox).
    # Defaults to the requesting eval/admin user when omitted.
    on_behalf_of_clinician_id: Optional[uuid.UUID] = None
    # Admin/eval bulk runs auto-advance Stage 2 by default (full multimodal
    # note without a manual Stage 1 approval). Final approval stays human.
    auto_advance_stage2: bool = True


@router.post("", response_model=CreateVideoImportResponse)
async def admin_create_video_import(
    body: AdminCreateVideoImportRequest,
    _: None = Depends(_require_enabled),
    actor: CurrentUser = Depends(require_role(UserRole.ADMIN, UserRole.EVAL_TEAM)),
    db: AsyncSession = Depends(get_db),
):
    if not body.consent_attested:
        raise HTTPException(
            status_code=400,
            detail="consent_attested must be true — consent is a hard gate.",
        )
    clinician_id = body.on_behalf_of_clinician_id or actor.user_id
    return await create_import_session(
        db,
        clinician_id=clinician_id,
        actor_id=actor.user_id,
        body=body,
        auto_advance_stage2=body.auto_advance_stage2,
    )


@router.post("/{session_id}/process", response_model=VideoImportStatusResponse)
async def admin_process_video_import(
    session_id: uuid.UUID,
    _: None = Depends(_require_enabled),
    actor: CurrentUser = Depends(require_role(UserRole.ADMIN, UserRole.EVAL_TEAM)),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_or_404(db, session_id)
    return await start_processing(db, session, actor_id=actor.user_id)


@router.get("/{session_id}/status", response_model=VideoImportStatusResponse)
async def admin_get_video_import_status(
    session_id: uuid.UUID,
    _: None = Depends(_require_enabled),
    actor: CurrentUser = Depends(require_role(UserRole.ADMIN, UserRole.EVAL_TEAM)),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_or_404(db, session_id)
    job = await jobs.get_job_for_session(db, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No import job for session.")
    await _reap_stale_job(db, job, session_id)
    return _status_response(session, job)
