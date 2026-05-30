"""Template override store (issue #72 foundation).

Mirrors the shape of ``app/modules/config/provider_overrides.py``: thin
async helpers over a single table, no cache logic here. Runtime
integration (in-memory cache + ~10s poller, mirroring
``provider_overrides.start_polling``) lands in a follow-up PR so this
foundation stays scoped.

Until that follow-up, an override written via PUT does not yet flow into
the running ``load_templates()`` cache — the disk JSON remains the
source of truth for the pipeline. Callers that need the "effective"
template right now (e.g. the admin GET endpoint) should call
``get_effective_template`` here, which checks DB first.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import TemplateOverrideModel
from app.core.types import Template
from app.modules.note_gen.service import load_templates

logger = logging.getLogger("aurion.note_gen.template_overrides")


async def list_overrides(db: AsyncSession) -> dict[str, Template]:
    """Return every persisted override, keyed by template_key."""
    result = await db.execute(select(TemplateOverrideModel))
    out: dict[str, Template] = {}
    for row in result.scalars().all():
        try:
            out[row.template_key] = Template(**row.content)
        except Exception as exc:  # noqa: BLE001 — best-effort merge
            logger.warning(
                "skipping malformed override row template_key=%s: %s",
                row.template_key,
                exc,
            )
    return out


async def get_override(db: AsyncSession, template_key: str) -> Template | None:
    """Return the persisted override for ``template_key``, or None."""
    result = await db.execute(
        select(TemplateOverrideModel).where(
            TemplateOverrideModel.template_key == template_key
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return Template(**row.content)


async def upsert_override(
    db: AsyncSession,
    template_key: str,
    template: Template,
    updated_by: uuid.UUID | None,
) -> Template:
    """Insert or update the override for ``template_key``.

    The caller is responsible for the audit-log write (template_changed).
    """
    if template.key != template_key:
        raise ValueError(
            f"template.key '{template.key}' does not match path key '{template_key}'"
        )
    result = await db.execute(
        select(TemplateOverrideModel).where(
            TemplateOverrideModel.template_key == template_key
        )
    )
    row = result.scalar_one_or_none()
    payload = template.model_dump()
    if row is None:
        db.add(
            TemplateOverrideModel(
                template_key=template_key,
                content=payload,
                updated_by=updated_by,
                updated_at=utcnow(),
            )
        )
    else:
        row.content = payload
        row.updated_by = updated_by
        row.updated_at = utcnow()
    await db.flush()
    return template


async def delete_override(db: AsyncSession, template_key: str) -> bool:
    """Remove the override; return True if a row was deleted."""
    result = await db.execute(
        select(TemplateOverrideModel).where(
            TemplateOverrideModel.template_key == template_key
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def get_effective_template(
    db: AsyncSession, template_key: str
) -> Template | None:
    """Return the override if one exists, otherwise the disk-bundled
    default. Useful for the admin GET endpoint to render the "what would
    the pipeline use today" view — even before the runtime integration
    follow-up flips the pipeline to honour overrides."""
    override = await get_override(db, template_key)
    if override is not None:
        return override
    return load_templates().get(template_key)
