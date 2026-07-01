"""Org-wide visit-type -> template default map (admin API).

Admins set an org default template per visit type; it resolves as the layer
between a clinician's own visit-type default (a visit type's ``is_default``
context, #577) and the specialty default — see
``session.service.resolve_context_template_key``. Same elevatable role set as
System Templates (#578). A default may pin a built-in ``template_key`` OR a
SHARED custom template ``custom_template_id`` — never a private clinician
template, so an org default can't leak one clinician's template to the org.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import OrgVisitTypeTemplateModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.custom_templates.service import get_shared
from app.modules.note_gen.org_visit_type_templates import (
    delete_org_default,
    list_org_defaults,
    upsert_org_default,
)
from app.modules.note_gen.service import list_available_templates

router = APIRouter(prefix="/admin", tags=["admin"])

# Same elevatable curation set as System Templates (#578): CLINICAL_ADMIN joins
# ADMIN + COMPLIANCE_OFFICER for template curation, but not infra/security.
_ROLES = (UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER, UserRole.CLINICAL_ADMIN)


class OrgVisitTypeTemplateResponse(BaseModel):
    visit_type: str
    template_key: str | None = None
    custom_template_id: uuid.UUID | None = None
    updated_at: datetime | None = None


class OrgVisitTypeTemplateListResponse(BaseModel):
    items: list[OrgVisitTypeTemplateResponse]


class UpsertOrgVisitTypeTemplateRequest(BaseModel):
    """Exactly one of ``template_key`` / ``custom_template_id`` (XOR)."""

    template_key: str | None = None
    custom_template_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "UpsertOrgVisitTypeTemplateRequest":
        if (self.template_key is None) == (self.custom_template_id is None):
            raise ValueError(
                "Exactly one of template_key / custom_template_id is required"
            )
        return self


def _to_response(row: OrgVisitTypeTemplateModel) -> OrgVisitTypeTemplateResponse:
    return OrgVisitTypeTemplateResponse(
        visit_type=row.visit_type,
        template_key=row.template_key,
        custom_template_id=row.custom_template_id,
        updated_at=row.updated_at,
    )


@router.get(
    "/visit-type-templates", response_model=OrgVisitTypeTemplateListResponse
)
async def list_visit_type_templates(
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> OrgVisitTypeTemplateListResponse:
    """Every org visit-type -> template default."""
    rows = await list_org_defaults(db)
    return OrgVisitTypeTemplateListResponse(
        items=[_to_response(r) for r in rows]
    )


@router.put(
    "/visit-type-templates/{visit_type}",
    response_model=OrgVisitTypeTemplateResponse,
)
async def upsert_visit_type_template(
    visit_type: str,
    body: UpsertOrgVisitTypeTemplateRequest,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> OrgVisitTypeTemplateResponse:
    """Set the org default template for ``visit_type``.

    ``template_key`` must be a built-in; ``custom_template_id`` must be an
    existing SHARED (org-usable) custom template — a private clinician template
    is rejected so an org default can never leak one clinician's template.
    """
    if body.template_key is not None:
        if body.template_key not in list_available_templates():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"template_key '{body.template_key}' is not an available "
                    "template"
                ),
            )
    else:
        shared = await get_shared(body.custom_template_id, db)
        if shared is None:
            raise HTTPException(
                status_code=422,
                detail="custom_template_id must be an existing shared template",
            )

    row = await upsert_org_default(
        db,
        visit_type,
        template_key=body.template_key,
        custom_template_id=body.custom_template_id,
        updated_by=user.user_id,
    )
    # Reuse TEMPLATE_CHANGED (the global template-admin event); new_specialty
    # carries the visit_type key for this org-map change.
    await write_audit(
        "system", AuditEventType.TEMPLATE_CHANGED, new_specialty=visit_type
    )
    return _to_response(row)


@router.delete(
    "/visit-type-templates/{visit_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_visit_type_template(
    visit_type: str,
    user: CurrentUser = Depends(require_role(*_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the org default for ``visit_type`` (idempotent)."""
    deleted = await delete_org_default(db, visit_type)
    if deleted:
        await write_audit(
            "system", AuditEventType.TEMPLATE_CHANGED, new_specialty=visit_type
        )
