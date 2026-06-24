"""Prompt Studio — admin authoring API (PS-03, part of create & share MVP #524).

ADMIN-only endpoints to author or upload a prompt from scratch and save edits
as new versions. A prompt is a named candidate bound to an AI job (a key in
``app.modules.prompts.registry.PROMPTS``); its text lives in append-only
``studio_prompt_versions`` rows.

Scope (thin MVP slice):
  * GET  /jobs                       — the registry jobs + their live default
                                       text (so the editor can "start from
                                       current").
  * GET  /prompts                    — the library: authored prompts by job.
  * GET  /prompts/{id}               — one prompt + its version history.
  * POST /prompts                    — create a prompt + its first version.
  * POST /prompts/{id}/versions      — save a new version (append-only).

Deferred to ps-05: publish/rollout, the ``prompt_studio_enabled`` feature flag
+ configurable role allowlist (this slice is ADMIN-only), and audit events.
Authoring a prompt is inert — nothing reaches a clinician's note until a
version is published.

Safety: every saved text passes ``validate_user_prompt`` (length + banlist +
descriptive-mode anchors), the SAME gate the per-physician override path uses,
and returns the SAME 400 detail shape the web already parses
(``parseGuidanceError``). A prompt that would strip the descriptive-mode
boundary is rejected before any row is written.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import StudioPromptModel, StudioPromptVersionModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.prompts import PROMPTS, ValidationCode, validate_user_prompt

router = APIRouter(prefix="/admin/prompt-studio", tags=["admin"])


# ── Wire shapes ──────────────────────────────────────────────────────────────


class StudioJobResponse(BaseModel):
    """One AI job a prompt can target, plus the text it currently uses by
    default — so the editor can offer "start from current" without a second
    call."""

    job_id: str
    name: str
    system_prompt: str


class StudioPromptVersionResponse(BaseModel):
    id: str
    version_no: int
    text: str
    created_at: datetime


class StudioPromptSummary(BaseModel):
    """Library row — one authored prompt, with its latest version number."""

    id: str
    job_id: str
    name: str
    latest_version_no: int
    created_at: datetime


class StudioPromptDetail(BaseModel):
    id: str
    job_id: str
    name: str
    created_at: datetime
    versions: list[StudioPromptVersionResponse]


class CreatePromptRequest(BaseModel):
    job_id: str = Field(description="Registry job this prompt targets.")
    name: str = Field(description="Display name for the prompt.")
    text: str = Field(
        description=(
            "The full standalone system prompt — authored, pasted, or "
            "uploaded. Validated structurally before any row is written."
        )
    )


class SaveVersionRequest(BaseModel):
    text: str = Field(description="The new version's full prompt text.")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _validated(text: str) -> str:
    """Strip + run the descriptive-mode safety gate, or raise 400.

    Same validator and same 400 detail shape (``message`` / ``code`` /
    ``matched_phrase`` / ``missing_anchor_group``) as the per-physician
    override path in ``me_prompts.py`` — the web parses both identically.
    """
    cleaned = text.strip() if text else ""
    result = validate_user_prompt(cleaned)
    if result.code is not ValidationCode.OK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": result.message,
                "code": result.code.value,
                "matched_phrase": result.matched_phrase,
                "missing_anchor_group": result.missing_anchor_group,
            },
        )
    return cleaned


def _job_or_404(job_id: str) -> None:
    if job_id not in PROMPTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )


def _version_response(v: StudioPromptVersionModel) -> StudioPromptVersionResponse:
    return StudioPromptVersionResponse(
        id=str(v.id),
        version_no=v.version_no,
        text=v.text,
        created_at=v.created_at,
    )


async def _prompt_or_404(
    db: AsyncSession, prompt_id: uuid.UUID
) -> StudioPromptModel:
    sp = await db.get(StudioPromptModel, prompt_id)
    if sp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown prompt: {prompt_id}",
        )
    return sp


# ── Reads ────────────────────────────────────────────────────────────────────


@router.get("/jobs", response_model=list[StudioJobResponse])
async def list_jobs(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> list[StudioJobResponse]:
    """The AI jobs a prompt can target + each job's current default text."""
    return [
        StudioJobResponse(job_id=p.id, name=p.name, system_prompt=p.system_prompt)
        for p in PROMPTS.values()
    ]


@router.get("/prompts", response_model=list[StudioPromptSummary])
async def list_prompts(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[StudioPromptSummary]:
    """The library: every (non-archived) authored prompt + its latest version
    number, newest first. One grouped query — no N+1."""
    result = await db.execute(
        select(
            StudioPromptModel,
            func.max(StudioPromptVersionModel.version_no),
        )
        .outerjoin(
            StudioPromptVersionModel,
            StudioPromptVersionModel.studio_prompt_id == StudioPromptModel.id,
        )
        .where(StudioPromptModel.archived_at.is_(None))
        .group_by(StudioPromptModel.id)
        .order_by(StudioPromptModel.created_at.desc())
    )
    return [
        StudioPromptSummary(
            id=str(sp.id),
            job_id=sp.job_id,
            name=sp.name,
            latest_version_no=latest or 0,
            created_at=sp.created_at,
        )
        for sp, latest in result.all()
    ]


@router.get("/prompts/{prompt_id}", response_model=StudioPromptDetail)
async def get_prompt(
    prompt_id: uuid.UUID,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> StudioPromptDetail:
    """One prompt + its full version history (oldest first)."""
    sp = await _prompt_or_404(db, prompt_id)
    versions = (
        await db.execute(
            select(StudioPromptVersionModel)
            .where(StudioPromptVersionModel.studio_prompt_id == prompt_id)
            .order_by(StudioPromptVersionModel.version_no)
        )
    ).scalars().all()
    return StudioPromptDetail(
        id=str(sp.id),
        job_id=sp.job_id,
        name=sp.name,
        created_at=sp.created_at,
        versions=[_version_response(v) for v in versions],
    )


# ── Writes ───────────────────────────────────────────────────────────────────


@router.post(
    "/prompts",
    response_model=StudioPromptDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt(
    body: CreatePromptRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> StudioPromptDetail:
    """Create a prompt for a job + its first version (v1).

    404 for an unknown ``job_id``; 400 (with the matched phrase / missing
    anchor) when the text fails the descriptive-mode safety gate.
    """
    _job_or_404(body.job_id)
    text = _validated(body.text)
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Name is required.", "code": "empty"},
        )

    sp = StudioPromptModel(
        id=uuid.uuid4(),
        job_id=body.job_id,
        name=name,
        created_by=user.user_id,
    )
    db.add(sp)
    await db.flush()
    ver = StudioPromptVersionModel(
        id=uuid.uuid4(),
        studio_prompt_id=sp.id,
        version_no=1,
        text=text,
        created_by=user.user_id,
    )
    db.add(ver)
    await db.flush()
    await db.commit()
    return StudioPromptDetail(
        id=str(sp.id),
        job_id=sp.job_id,
        name=sp.name,
        created_at=sp.created_at,
        versions=[_version_response(ver)],
    )


@router.post(
    "/prompts/{prompt_id}/versions",
    response_model=StudioPromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_version(
    prompt_id: uuid.UUID,
    body: SaveVersionRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> StudioPromptVersionResponse:
    """Append a new version to an existing prompt (monotonic ``version_no``).

    404 for an unknown prompt; 400 when the text fails the safety gate.
    """
    await _prompt_or_404(db, prompt_id)
    text = _validated(body.text)
    current_max = (
        await db.execute(
            select(func.max(StudioPromptVersionModel.version_no)).where(
                StudioPromptVersionModel.studio_prompt_id == prompt_id
            )
        )
    ).scalar()
    ver = StudioPromptVersionModel(
        id=uuid.uuid4(),
        studio_prompt_id=prompt_id,
        version_no=(current_max or 0) + 1,
        text=text,
        created_by=user.user_id,
    )
    db.add(ver)
    await db.flush()
    await db.commit()
    return _version_response(ver)
