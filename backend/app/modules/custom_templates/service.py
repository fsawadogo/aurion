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


def _schema_error_msg(exc: ValidationError) -> str:
    """Compact, input-free summary of a Pydantic ``ValidationError``.

    Joins each error's location + message but NEVER the offending input value
    (clinician-authored content). Pydantic's default ``str(exc)`` interpolates
    ``input_value=...``, so we format from ``.errors()`` to keep submitted text
    out of the 4xx response body.
    """
    parts = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e.get("loc", ())) or "template"
        parts.append(f"{loc}: {e.get('msg', 'invalid')}")
    summary = "; ".join(parts) or "invalid template"
    return f"Template failed schema validation ({summary})"


# Field caps for CUSTOM templates only — deliberately NOT applied to the base
# `Template` schema, which the trusted on-disk built-in specialty templates
# also flow through (tightening that schema could break note generation).
#
# Two tiers, enforced differently (see `_validate_custom_template_fields`):
#   * key / display_name / version — mirror the `custom_templates` String(50)/
#     (100)/(20) columns, so over-long input would DataError->500 at flush.
#     Enforced on EVERY write (create + update). Plus the >=1-section rule.
#   * section length/count caps — NOT DB-backed (sections live in the unbounded
#     `content` JSON Text column). These are create-time PRODUCT limits only:
#     enforcing them on update would lock a clinician out of editing a template
#     whose sections predate the caps (even a metadata-only rename re-validates
#     the whole body), so the update path skips them.
_KEY_MAX = 50
_DISPLAY_NAME_MAX = 100
_VERSION_MAX = 20
_SECTION_ID_MAX = 50
_SECTION_TITLE_MAX = 100
_SECTION_DESC_MAX = 500
_KEYWORD_MAX = 50
_MAX_SECTIONS = 50
_MAX_KEYWORDS_PER_SECTION = 50


def _validate_custom_template_fields(
    template: Template, *, check_section_caps: bool = True
) -> None:
    """Enforce custom-template field caps. Raises ``CustomTemplateError`` (→400).

    DB-backed caps (key/display_name/version) and the >=1-section rule run on
    every write. The section-level length/count caps are create-time product
    limits and are skipped when ``check_section_caps`` is False (the update
    path) so a pre-existing over-cap template stays editable.
    """
    key = (template.key or "").strip()
    if not key:
        raise CustomTemplateError("Template key is required")
    if len(key) > _KEY_MAX:
        raise CustomTemplateError(f"Template key exceeds {_KEY_MAX} characters")
    name = (template.display_name or "").strip()
    if not name:
        raise CustomTemplateError("Template display name is required")
    if len(name) > _DISPLAY_NAME_MAX:
        raise CustomTemplateError(
            f"Template display name exceeds {_DISPLAY_NAME_MAX} characters"
        )
    if len(template.version or "") > _VERSION_MAX:
        raise CustomTemplateError(
            f"Template version exceeds {_VERSION_MAX} characters"
        )
    if not template.sections:
        raise CustomTemplateError("Template must have at least one section")
    if not check_section_caps:
        return
    if len(template.sections) > _MAX_SECTIONS:
        raise CustomTemplateError(f"Template exceeds {_MAX_SECTIONS} sections")
    for sec in template.sections:
        sid = (sec.id or "").strip()
        if not sid:
            raise CustomTemplateError("Each section needs an id")
        if len(sid) > _SECTION_ID_MAX:
            raise CustomTemplateError(
                f"Section id exceeds {_SECTION_ID_MAX} characters"
            )
        title = (sec.title or "").strip()
        if not title:
            raise CustomTemplateError("Each section needs a title")
        if len(title) > _SECTION_TITLE_MAX:
            raise CustomTemplateError(
                f"Section title exceeds {_SECTION_TITLE_MAX} characters"
            )
        if len(sec.description or "") > _SECTION_DESC_MAX:
            raise CustomTemplateError(
                f"Section description exceeds {_SECTION_DESC_MAX} characters"
            )
        if len(sec.visual_trigger_keywords) > _MAX_KEYWORDS_PER_SECTION:
            raise CustomTemplateError(
                f"A section has more than {_MAX_KEYWORDS_PER_SECTION} keywords"
            )
        for kw in sec.visual_trigger_keywords:
            if len(kw) > _KEYWORD_MAX:
                raise CustomTemplateError(
                    f"A visual-trigger keyword exceeds {_KEYWORD_MAX} characters"
                )


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
        raise CustomTemplateError(_schema_error_msg(exc)) from exc
    _validate_custom_template_fields(template)

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
        raise CustomTemplateError(_schema_error_msg(exc)) from exc
    # check_section_caps=False on update: the section length/count caps aren't
    # DB-backed and re-validating the whole body on every edit would lock a
    # clinician out of a template whose sections predate the caps (incl. a
    # metadata-only rename). DB-backed caps + the >=1-section rule still apply.
    _validate_custom_template_fields(template, check_section_caps=False)

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

    `CustomTemplateModel` has no is_active column, so this is a hard
    delete. The trail is preserved out-of-band: the route writes an
    append-only ``CUSTOM_TEMPLATE_DELETED`` audit event (DynamoDB) before
    committing, so the lifecycle stays reconstructable. A follow-up PR can
    add an is_active column and flip this to a soft delete if needed.
    """
    await db.delete(row)
    await db.flush()


# ── Internals ──────────────────────────────────────────────────────────────


async def _find_by_owner_and_key(
    owner_id: uuid.UUID, key: str, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    # `.first()` (not `scalar_one_or_none`) so a pre-existing duplicate
    # (owner_id, key) pair — possible from the old finalize path that
    # skipped this check — reports "already exists" rather than blowing up
    # the uniqueness probe itself with MultipleResultsFound (500).
    stmt = (
        select(CustomTemplateModel)
        .where(
            CustomTemplateModel.owner_id == owner_id,
            CustomTemplateModel.key == key,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


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
