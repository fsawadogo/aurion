"""Admin shared / org templates (tpl-04).

An ADMIN authors a note template marked ``is_shared=True`` that surfaces
read-only in every clinician's library + the upload / visit-type picker (via
``list_for_owner(include_shared=True)``) and resolves at note generation via
``get_owned_or_shared``. The row is owned by the creating admin; clinicians can
apply it but never edit or delete it.

ADMIN-only — authoring org-wide clinical content. The system-template surface
(``admin/templates.py``) handles built-in specialty templates; this handles
shared *custom* templates. Validation (incl. the descriptive-mode gate on any
AI instructions, tpl-01) is reused from the custom-templates service.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.types import UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, require_role
from app.modules.custom_templates import service as svc

router = APIRouter(prefix="/admin", tags=["admin"])

_ROLE = UserRole.ADMIN


class SharedTemplateResponse(BaseModel):
    """Wire shape for a shared org template — mirrors me.py
    CustomTemplateResponse so the web reuses the ``CustomTemplate`` type."""

    id: str
    key: str
    display_name: str
    version: str
    owner_id: str
    is_shared: bool
    template: dict[str, Any]
    created_at: str
    updated_at: str


class SharedTemplateCreateRequest(BaseModel):
    template: dict[str, Any] = Field(
        ..., description="Template JSON matching the Template schema"
    )


def _to_response(row: Any) -> SharedTemplateResponse:
    return SharedTemplateResponse(
        id=str(row.id),
        key=row.key,
        display_name=row.display_name,
        version=row.version,
        owner_id=str(row.owner_id),
        is_shared=row.is_shared,
        template=json.loads(row.content),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/shared-templates", response_model=list[SharedTemplateResponse])
async def list_shared_templates(
    _: CurrentUser = Depends(require_role(_ROLE)),
    db: AsyncSession = Depends(get_db),
) -> list[SharedTemplateResponse]:
    """List every shared org template (admin management view)."""
    rows = await svc.list_shared(db)
    return [_to_response(r) for r in rows]


@router.post(
    "/shared-templates",
    response_model=SharedTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_shared_template(
    body: SharedTemplateCreateRequest,
    user: CurrentUser = Depends(require_role(_ROLE)),
    db: AsyncSession = Depends(get_db),
) -> SharedTemplateResponse:
    """Author a shared org template (owned by the admin, ``is_shared=True``).

    Reuses the custom-template validation — including the descriptive-mode gate
    on any AI instructions (tpl-01). 400 on schema / safety failure, 409 on a
    duplicate key for this admin.
    """
    try:
        row = await svc.create_for_owner(
            user.user_id, body.template, db, is_shared=True
        )
    except svc.CustomTemplateError as exc:
        msg = str(exc)
        raise HTTPException(
            status_code=409 if "already exists" in msg else 400, detail=msg
        ) from exc
    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(row.id),
        event_type=AuditEventType.CUSTOM_TEMPLATE_CREATED,
        actor_id=str(user.user_id),
        template_id=str(row.id),
        template_key=row.key,
    )
    await db.commit()
    return _to_response(row)


@router.delete(
    "/shared-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_shared_template(
    template_id: uuid.UUID,
    user: CurrentUser = Depends(require_role(_ROLE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a shared org template. 404 if it isn't a shared row — so this
    path can never reach a clinician's private template."""
    row = await svc.get_shared(template_id, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Shared template not found")
    key = row.key
    await svc.delete_owned(row, db)
    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(template_id),
        event_type=AuditEventType.CUSTOM_TEMPLATE_DELETED,
        actor_id=str(user.user_id),
        template_id=str(template_id),
        template_key=key,
    )
    await db.commit()
