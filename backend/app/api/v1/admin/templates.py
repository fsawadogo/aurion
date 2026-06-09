"""Template + visual-trigger keyword management (issue #72 foundation).

Storage + CRUD over the disk-bundled specialty templates. PUT/DELETE
writes go through the ``template_overrides`` repo AND the runtime cache
(#72): the serving task honours the edit immediately via
``set_cached``/``clear_cached``; other tasks converge within ~10s via
``template_override_cache``'s poller. ``get_template()`` resolves
override > disk, so edits are live in the note pipeline without a
restart.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.types import Template, UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.note_gen.service import load_templates
from app.modules.note_gen.template_override_cache import (
    clear_cached,
    set_cached,
)
from app.modules.note_gen.template_overrides import (
    delete_override,
    get_effective_template,
    list_overrides,
    upsert_override,
)

router = APIRouter(prefix="/admin", tags=["admin"])


_ROLES = (UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)


class TemplateSummaryResponse(BaseModel):
    template_key: str
    display_name: str
    version: str
    section_count: int
    is_override: bool


class TemplateListResponse(BaseModel):
    items: list[TemplateSummaryResponse]


class TemplateDetailResponse(BaseModel):
    template: Template
    is_override: bool
    updated_at: datetime | None
    note: str = (
        "Edits are live: the note pipeline resolves admin overrides ahead "
        "of the disk-bundled template (immediately on this task, within "
        "~10s fleet-wide)."
    )


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> TemplateListResponse:
    """List every known template — bundled + any admin override.

    Disk-bundled templates always appear; ``is_override`` reflects whether
    an admin has saved a custom version.
    """
    bundled = load_templates()
    overrides = await list_overrides(db)

    items: list[TemplateSummaryResponse] = []
    for key in sorted(set(bundled.keys()) | set(overrides.keys())):
        # An override wins for display when both exist; this matches what
        # the future runtime cache will resolve to.
        effective = overrides.get(key) or bundled.get(key)
        if effective is None:  # pragma: no cover — set-union guards above
            continue
        items.append(
            TemplateSummaryResponse(
                template_key=key,
                display_name=effective.display_name,
                version=effective.version,
                section_count=len(effective.sections),
                is_override=key in overrides,
            )
        )
    return TemplateListResponse(items=items)


@router.get("/templates/{template_key}", response_model=TemplateDetailResponse)
async def get_template_detail(
    template_key: str,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> TemplateDetailResponse:
    """Return the effective template for ``template_key``.

    Override wins over disk default; 404 if neither exists.
    """
    effective = await get_effective_template(db, template_key)
    if effective is None:
        raise HTTPException(
            status_code=404, detail=f"No template named '{template_key}'"
        )
    overrides = await list_overrides(db)
    return TemplateDetailResponse(
        template=effective,
        is_override=template_key in overrides,
        updated_at=None,  # follow-up: return the override row's updated_at
    )


@router.put("/templates/{template_key}", response_model=TemplateDetailResponse)
async def upsert_template(
    template_key: str,
    body: Template,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> TemplateDetailResponse:
    """Insert or update the override for ``template_key``.

    Pydantic validates the body against the ``Template`` schema before
    persistence — a malformed payload cannot corrupt the override store.
    A ``TEMPLATE_CHANGED`` audit event is written on success.
    """
    if body.key != template_key:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Body template.key '{body.key}' does not match path "
                f"key '{template_key}'"
            ),
        )
    saved = await upsert_override(db, template_key, body, updated_by=user.user_id)
    # #72 runtime integration: the serving task honours the edit
    # immediately; the rest of the fleet converges via the ~10s poller.
    set_cached(template_key, saved)
    await write_audit(
        # No session_id is meaningful here — use a sentinel UUID matching
        # how other "global" admin actions audit (see provider_overrides
        # upsert_override which audits against "system").
        "system",
        AuditEventType.TEMPLATE_CHANGED,
        new_specialty=template_key,
    )
    return TemplateDetailResponse(
        template=saved,
        is_override=True,
        updated_at=None,
    )


@router.delete(
    "/templates/{template_key}", status_code=status.HTTP_204_NO_CONTENT
)
async def revert_template(
    template_key: str,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete the override and revert ``template_key`` to its disk default.

    If no override exists, returns 204 anyway (idempotent).
    """
    deleted = await delete_override(db, template_key)
    # Always evict — idempotent like the delete itself, and it heals a
    # cache entry that somehow outlived its row.
    clear_cached(template_key)
    if deleted:
        await write_audit(
            "system",
            AuditEventType.TEMPLATE_CHANGED,
            new_specialty=template_key,
        )
