"""Clinician self-serve: my correction memory.

Read-only view of the corrections captured from a clinician's own in-app note
edits (``correction_memory_enabled``). This is the clinician-facing window onto
the moat: "here is what you keep changing." The classification + rule-suggestion
layer builds on top of these rows later.

Owner-scoped: a clinician sees ONLY their own corrections (``clinician_id ==
user.user_id``). The before/after text is note content (PHI) the clinician
already owns; nothing cross-clinician is reachable here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import CorrectionModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.appconfig_client import get_config
from app.modules.corrections.classify import classify_pending_for_clinician

router = APIRouter(prefix="/me", tags=["me"])


async def require_clinician(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.role is not UserRole.CLINICIAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This surface is for clinicians.",
        )
    return user


class CorrectionItem(BaseModel):
    id: str
    session_id: str
    section_id: str
    before_text: str
    after_text: str
    classification: str | None = None
    note_version: int | None = None
    created_at: str


class CorrectionsResponse(BaseModel):
    items: list[CorrectionItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    enabled: bool  # whether correction_memory_enabled is on


@router.get("/corrections", response_model=CorrectionsResponse)
async def list_my_corrections(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> CorrectionsResponse:
    """List the clinician's own captured corrections, newest first.

    Returns an empty list (``enabled=false``) when the feature is dark, so the
    UI can show a "not enabled" state without a separate probe.
    """
    enabled = get_config().feature_flags.correction_memory_enabled

    base = select(CorrectionModel).where(
        CorrectionModel.clinician_id == user.user_id
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    rows = (
        await db.execute(
            base.order_by(CorrectionModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [
        CorrectionItem(
            id=str(r.id),
            session_id=str(r.session_id),
            section_id=r.section_id,
            before_text=r.before_text,
            after_text=r.after_text,
            classification=r.classification,
            note_version=r.note_version,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
    return CorrectionsResponse(
        items=items, total=total, page=page, page_size=page_size, enabled=enabled
    )


class ClassifyResponse(BaseModel):
    """Per-label counts from a classification pass."""

    typo: int = 0
    semantic: int = 0
    medical: int = 0
    skipped: int = 0


@router.post("/corrections/classify", response_model=ClassifyResponse)
async def classify_my_corrections(
    limit: int = Query(100, ge=1, le=500),
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> ClassifyResponse:
    """Classify the clinician's still-unclassified corrections (typo / semantic
    / medical). ADMIN can't reach this — it's the clinician's own data.

    Flag-gated: 409 when ``correction_memory_enabled`` is off (no corrections
    are being captured, so there is nothing to classify). Each label is filled
    on its row; the response is the per-label count from this pass.
    """
    if not get_config().feature_flags.correction_memory_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Correction memory is not enabled.",
        )
    counts = await classify_pending_for_clinician(user.user_id, db, limit=limit)
    return ClassifyResponse(**counts)
