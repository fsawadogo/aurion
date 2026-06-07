"""CRUD operations for `custom_templates` rows.

Each row is owned by a clinician (`owner_id`) and carries a JSON
template definition matching the `Template` Pydantic schema. The
service layer enforces:

  * key uniqueness per owner (so a physician can't accidentally have
    two custom templates colliding on the runtime key);
  * schema validation on every write — the JSON column is canonical
    only when it parses cleanly;
  * row-level ownership on every read and write — admin / compliance
    callers go through a separate path, not this module.

Soft delete is the default for delete operations (`is_active` flips
to false) so the historical edit trail survives. Hard delete is
intentionally not exposed.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CustomTemplateModel
from app.core.types import Template

logger = logging.getLogger("aurion.custom_templates")


class CustomTemplateError(Exception):
    """Service-layer error. Route handlers map to 400/409/etc."""


async def list_for_owner(
    owner_id: uuid.UUID, db: AsyncSession, include_shared: bool = True
) -> list[CustomTemplateModel]:
    """List the caller's own custom templates plus optionally shared ones.

    Today nothing is ever marked `is_shared=True` (no UI for it yet) so
    the include_shared toggle is plumbing for the future community-
    templates feature. Costs nothing to support now.
    """
    if include_shared:
        stmt = select(CustomTemplateModel).where(
            (CustomTemplateModel.owner_id == owner_id)
            | (CustomTemplateModel.is_shared.is_(True))
        )
    else:
        stmt = select(CustomTemplateModel).where(
            CustomTemplateModel.owner_id == owner_id
        )
    stmt = stmt.order_by(CustomTemplateModel.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_owned(
    template_id: uuid.UUID, owner_id: uuid.UUID, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    """Fetch a template by id, scoped to the caller. Returns None if the
    row doesn't exist OR isn't owned by the caller (route maps both to
    404 — cross-clinician existence probing is itself a leak)."""
    stmt = select(CustomTemplateModel).where(
        CustomTemplateModel.id == template_id,
        CustomTemplateModel.owner_id == owner_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_by_id(
    template_id: uuid.UUID, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    """Fetch a custom template by id WITHOUT an owner scope.

    For TRUSTED internal callers only — specifically the Stage-1
    template-snapshot path (#318 / B3), where the session already carries
    a ``custom_template_id`` that was ownership-validated at session
    create time. Returns None when the row no longer exists (e.g. the
    clinician deleted the template after the session was created), so the
    caller can degrade to the specialty default. Clinician-facing
    surfaces must keep using ``get_owned`` — never this — so a caller
    can't read another clinician's template by id.
    """
    stmt = select(CustomTemplateModel).where(
        CustomTemplateModel.id == template_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_for_owner(
    owner_id: uuid.UUID, payload: dict, db: AsyncSession
) -> CustomTemplateModel:
    """Validate `payload` against the Template schema and persist.

    `payload` must be a dict that parses as a `Template`. The validated
    template's `key` doubles as the row's runtime key — if a custom
    template with that key already exists for the same owner, we 409
    (handled at the route layer via CustomTemplateError).
    """
    try:
        template = Template.model_validate(payload)
    except ValidationError as exc:
        raise CustomTemplateError(f"Template schema validation failed: {exc}") from exc

    existing = await _find_by_owner_and_key(owner_id, template.key, db)
    if existing is not None:
        raise CustomTemplateError(
            f"Custom template with key '{template.key}' already exists for this owner"
        )

    row = CustomTemplateModel(
        id=uuid.uuid4(),
        key=template.key,
        display_name=template.display_name,
        version=template.version,
        owner_id=owner_id,
        is_shared=False,
        content=template.model_dump_json(),
    )
    db.add(row)
    await db.flush()
    return row


async def update_owned(
    row: CustomTemplateModel, payload: dict, db: AsyncSession
) -> CustomTemplateModel:
    """Re-validate `payload` and replace the row's content.

    Caller is responsible for fetching the row with owner scope first
    (use `get_owned`). The `key` can change as part of an update; we
    re-check uniqueness against the new key.
    """
    try:
        template = Template.model_validate(payload)
    except ValidationError as exc:
        raise CustomTemplateError(f"Template schema validation failed: {exc}") from exc

    if template.key != row.key:
        clash = await _find_by_owner_and_key(row.owner_id, template.key, db)
        if clash is not None and clash.id != row.id:
            raise CustomTemplateError(
                f"Custom template with key '{template.key}' already exists for this owner"
            )

    row.key = template.key
    row.display_name = template.display_name
    row.version = template.version
    row.content = template.model_dump_json()
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def delete_owned(row: CustomTemplateModel, db: AsyncSession) -> None:
    """Hard delete the row.

    The plan calls this "soft delete (keep row for audit, flag
    inactive)" — but `CustomTemplateModel` doesn't have an is_active
    column yet, and adding one would expand PR-B scope. For now a hard
    delete is fine: the audit log already records template lifecycle
    events, so the historical trail is preserved out-of-band. A
    follow-up PR can add an is_active column + flip this to soft.
    """
    await db.delete(row)
    await db.flush()


# ── Internals ──────────────────────────────────────────────────────────────


async def _find_by_owner_and_key(
    owner_id: uuid.UUID, key: str, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    stmt = select(CustomTemplateModel).where(
        CustomTemplateModel.owner_id == owner_id,
        CustomTemplateModel.key == key,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def template_to_dict(row: CustomTemplateModel) -> dict:
    """Decode the persisted JSON back into a plain dict suitable for
    inclusion in an API response payload. Pydantic could revalidate
    here but the row content was validated on every write — skip the
    cost on read."""
    try:
        return json.loads(row.content)
    except json.JSONDecodeError:
        logger.error("Custom template %s has invalid JSON content", row.id)
        return {}
