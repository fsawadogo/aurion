"""Org-wide visit-type -> template default map (repo).

Thin async CRUD over ``org_visit_type_templates``. Consumed by the admin API on
write and by ``resolve_context_template_key`` on read, where it is the org-default
layer between a clinician's own visit-type default (a visit type's ``is_default``
context, #577) and the specialty default. Mutual exclusion (``template_key`` XOR
``custom_template_id``) + reference validity are enforced by the API on write;
this module is storage only.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import OrgVisitTypeTemplateModel


async def list_org_defaults(db: AsyncSession) -> list[OrgVisitTypeTemplateModel]:
    """Every org visit-type default, ordered by visit type."""
    result = await db.execute(
        select(OrgVisitTypeTemplateModel).order_by(
            OrgVisitTypeTemplateModel.visit_type
        )
    )
    return list(result.scalars().all())


async def get_org_default(
    db: AsyncSession, visit_type: str
) -> Optional[OrgVisitTypeTemplateModel]:
    """The org default for one visit type, or ``None``."""
    return (
        await db.execute(
            select(OrgVisitTypeTemplateModel).where(
                OrgVisitTypeTemplateModel.visit_type == visit_type
            )
        )
    ).scalar_one_or_none()


async def upsert_org_default(
    db: AsyncSession,
    visit_type: str,
    *,
    template_key: Optional[str],
    custom_template_id: Optional[uuid.UUID],
    updated_by: uuid.UUID,
) -> OrgVisitTypeTemplateModel:
    """Insert or update the org default for ``visit_type`` and commit.

    The caller (admin API) guarantees exactly one of ``template_key`` /
    ``custom_template_id`` is set and that it references a valid built-in / shared
    template.
    """
    row = await get_org_default(db, visit_type)
    if row is None:
        row = OrgVisitTypeTemplateModel(visit_type=visit_type)
        db.add(row)
    row.template_key = template_key
    row.custom_template_id = custom_template_id
    row.updated_by = updated_by
    await db.commit()
    await db.refresh(row)
    return row


async def delete_org_default(db: AsyncSession, visit_type: str) -> bool:
    """Delete the org default for ``visit_type`` and commit.

    Returns ``True`` when a row was removed, ``False`` when there was nothing to
    delete (idempotent).
    """
    result = await db.execute(
        sa_delete(OrgVisitTypeTemplateModel).where(
            OrgVisitTypeTemplateModel.visit_type == visit_type
        )
    )
    await db.commit()
    return (result.rowcount or 0) > 0
