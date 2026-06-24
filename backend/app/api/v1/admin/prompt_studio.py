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
  * POST /prompts/{id}/publish       — publish a version to a cohort.

Publishing (PS-05) moves a version into a cohort (self / role / all) and is the
consequential, audited action; authoring a draft is inert until then. Every
route is gated by ``feature_flags.prompt_studio_enabled`` + the
``prompt_studio_roles`` allowlist (default ADMIN).

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

from app.api.v1._helpers import raise_if_validation_failed, write_audit
from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.database import get_db
from app.core.models import (
    PromptPublicationModel,
    StudioPromptModel,
    StudioPromptVersionModel,
)
from app.core.types import PublicationScope, UserRole
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.appconfig_client import get_config
from app.modules.prompts import PROMPTS, validate_user_prompt

router = APIRouter(prefix="/admin/prompt-studio", tags=["admin"])

#: Prompt-config audit events aren't bound to a session — the all-zeros
#: sentinel keeps them out of any real session's history (matches me_prompts).
_PROMPT_AUDIT_SESSION_ID: str = "00000000-0000-0000-0000-000000000000"


async def require_prompt_studio(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Gate every Studio route: the feature flag must be ON and the caller's
    role must be in the allowlist (PS-05).

    Ships dark — ``feature_flags.prompt_studio_enabled`` defaults False, so the
    whole surface 403s until an operator flips it. ``prompt_studio_roles``
    (default ``["ADMIN"]``) lets the surface widen to EVAL_TEAM / CLINICIAN
    later via AppConfig without a redeploy. 403 (not 404) so the failure is
    legible to the portal, which hides the nav on the same signal.
    """
    flags = get_config().feature_flags
    if not flags.prompt_studio_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prompt Studio is not enabled.",
        )
    allowed = {r.upper() for r in (flags.prompt_studio_roles or ["ADMIN"])}
    if user.role.value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Prompt Studio is not available for role {user.role.value}.",
        )
    return user


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


class PublishRequest(BaseModel):
    version_id: uuid.UUID = Field(description="The version to publish.")
    scope: PublicationScope = Field(
        description="Who receives it: SELF (you), ROLE (a role), or ALL clinicians."
    )
    target_role: UserRole | None = Field(
        default=None,
        description="Required when scope=ROLE; ignored otherwise.",
    )


class PublicationResponse(BaseModel):
    id: str
    job_id: str
    version_id: str
    version_no: int
    scope: str
    target_role: str | None
    target_user_id: str | None
    published_at: datetime


# ── Helpers ──────────────────────────────────────────────────────────────────


def _validated(text: str) -> str:
    """Strip + run the descriptive-mode safety gate, or raise 400.

    Same validator and same 400 detail shape (``message`` / ``code`` /
    ``matched_phrase`` / ``missing_anchor_group``) as the per-physician
    override path in ``me_prompts.py`` — the web parses both identically.
    """
    cleaned = text.strip() if text else ""
    raise_if_validation_failed(validate_user_prompt(cleaned))
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
    user: CurrentUser = Depends(require_prompt_studio),
) -> list[StudioJobResponse]:
    """The AI jobs a prompt can target + each job's current default text."""
    return [
        StudioJobResponse(job_id=p.id, name=p.name, system_prompt=p.system_prompt)
        for p in PROMPTS.values()
    ]


@router.get("/prompts", response_model=list[StudioPromptSummary])
async def list_prompts(
    user: CurrentUser = Depends(require_prompt_studio),
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
    user: CurrentUser = Depends(require_prompt_studio),
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
    user: CurrentUser = Depends(require_prompt_studio),
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
    user: CurrentUser = Depends(require_prompt_studio),
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


@router.post(
    "/prompts/{prompt_id}/publish",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_prompt(
    prompt_id: uuid.UUID,
    body: PublishRequest,
    user: CurrentUser = Depends(require_prompt_studio),
    db: AsyncSession = Depends(get_db),
) -> PublicationResponse:
    """Publish a version to a cohort — SELF (the publisher's own sessions),
    ROLE (everyone of a role), or ALL clinicians (PS-05).

    Supersedes the prior active publication for the same ``(job, scope,
    target)`` by stamping ``superseded_at`` — the rollout history stays
    append-only. Writes ``PROMPT_STUDIO_PUBLISHED`` (provenance only, never
    the prompt text). Resolution (ps-02) reads the active publication, so the
    published text takes effect for clinicians without a personal override.
    """
    sp = await _prompt_or_404(db, prompt_id)
    version = await db.get(StudioPromptVersionModel, body.version_id)
    if version is None or version.studio_prompt_id != prompt_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown version for this prompt.",
        )
    if body.scope is PublicationScope.ROLE and body.target_role is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_role is required when scope=ROLE.",
        )

    target_user_id = user.user_id if body.scope is PublicationScope.SELF else None
    target_role = (
        body.target_role.value if body.scope is PublicationScope.ROLE else None
    )

    # Supersede the prior active publication for the same (job, scope, target)
    # — stamp, don't delete, so the rollout history stays auditable.
    existing = await db.execute(
        select(PromptPublicationModel).where(
            PromptPublicationModel.job_id == sp.job_id,
            PromptPublicationModel.scope == body.scope.value,
            PromptPublicationModel.target_user_id == target_user_id,
            PromptPublicationModel.target_role == target_role,
            PromptPublicationModel.superseded_at.is_(None),
        )
    )
    now = utcnow()
    for row in existing.scalars().all():
        row.superseded_at = now

    pub = PromptPublicationModel(
        id=uuid.uuid4(),
        job_id=sp.job_id,
        version_id=version.id,
        scope=body.scope.value,
        target_role=target_role,
        target_user_id=target_user_id,
        published_by=user.user_id,
    )
    db.add(pub)
    await db.flush()
    await write_audit(
        _PROMPT_AUDIT_SESSION_ID,
        AuditEventType.PROMPT_STUDIO_PUBLISHED,
        actor_id=str(user.user_id),
        job_id=sp.job_id,
        version_no=version.version_no,
        scope=body.scope.value,
        **({"target_role": target_role} if target_role else {}),
    )
    await db.commit()
    return PublicationResponse(
        id=str(pub.id),
        job_id=pub.job_id,
        version_id=str(pub.version_id),
        version_no=version.version_no,
        scope=pub.scope,
        target_role=pub.target_role,
        target_user_id=str(pub.target_user_id) if pub.target_user_id else None,
        published_at=pub.published_at,
    )
