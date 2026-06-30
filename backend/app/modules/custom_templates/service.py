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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CustomTemplateModel
from app.core.types import Template
from app.modules.prompts.safety import ValidationCode, validate_user_prompt

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
    # tpl-01: a template may carry note-gen instructions. When present they
    # REPLACE the note-gen system prompt at generation time, so they pass the
    # same descriptive-mode safety gate as a clinician's personal prompt
    # override. Empty / whitespace means "no instructions" (structure only).
    if template.system_prompt and template.system_prompt.strip():
        result = validate_user_prompt(template.system_prompt)
        if result.code is not ValidationCode.OK:
            raise CustomTemplateError(result.message)
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


async def get_owned_or_shared(
    template_id: uuid.UUID, owner_id: uuid.UUID, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    """Fetch a template by id when it's owned by the caller OR is a shared org
    template (``is_shared``). For clinician READ + the note-gen SELECTION paths
    (context binding, video-import picker) so an admin-created shared template
    the caller doesn't own still resolves. Edit/delete must keep using
    :func:`get_owned` — a clinician must never mutate a shared row.

    Narrower than :func:`get_by_id` (unscoped, trusted-callers-only): a *private*
    template owned by someone else is still not returned."""
    stmt = select(CustomTemplateModel).where(
        CustomTemplateModel.id == template_id,
        (CustomTemplateModel.owner_id == owner_id)
        | (CustomTemplateModel.is_shared.is_(True)),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_shared(
    template_id: uuid.UUID, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    """Fetch a shared org template by id (``is_shared=True``). For the admin
    shared-templates surface (manage / delete). Returns None for a non-shared
    row so that path can't touch a clinician's private template."""
    stmt = select(CustomTemplateModel).where(
        CustomTemplateModel.id == template_id,
        CustomTemplateModel.is_shared.is_(True),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_shared(db: AsyncSession) -> list[CustomTemplateModel]:
    """Every shared org template (``is_shared=True``), newest first. For the
    admin shared-templates management surface."""
    stmt = (
        select(CustomTemplateModel)
        .where(CustomTemplateModel.is_shared.is_(True))
        .order_by(CustomTemplateModel.updated_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _flush_mapping_unique(db: AsyncSession, key: str) -> None:
    """``db.flush()`` that maps the (owner_id, key) unique-constraint
    violation to a friendly ``CustomTemplateError`` (→ 409).

    The in-app ``_find_by_owner_and_key`` check catches the common case, but
    the DB constraint (uq_custom_templates_owner_key) is the race-proof
    guarantee — if two requests slip past the in-app check concurrently, the
    loser hits this and gets a clean 409 instead of an unhandled 500.
    """
    try:
        await db.flush()
    except IntegrityError as exc:
        # Match the constraint NAME only (asyncpg + psycopg2 both embed it in
        # str(orig), and it's locale-stable). A bare "unique" substring would
        # mislabel any other unique violation as a key clash.
        if "uq_custom_templates_owner_key" in str(getattr(exc, "orig", exc)):
            raise CustomTemplateError(
                f"Custom template with key '{key}' already exists for this owner"
            ) from exc
        raise


async def create_for_owner(
    owner_id: uuid.UUID, payload: dict, db: AsyncSession, *, is_shared: bool = False
) -> CustomTemplateModel:
    """Validate `payload` against the Template schema and persist.

    `payload` must be a dict that parses as a `Template`. The validated
    template's `key` doubles as the row's runtime key — if a custom
    template with that key already exists for the same owner, we 409
    (handled at the route layer via CustomTemplateError).

    `is_shared=True` marks an org/shared template (tpl-04): it then appears
    read-only in every clinician's library + picker via
    ``list_for_owner(include_shared=True)`` and resolves at note generation via
    ``get_owned_or_shared``. Only the admin shared-templates surface passes True.
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
        is_shared=is_shared,
        content=template.model_dump_json(),
    )
    db.add(row)
    await _flush_mapping_unique(db, template.key)
    return row


async def duplicate_into_owner(
    source_id: uuid.UUID, owner_id: uuid.UUID, db: AsyncSession
) -> Optional[CustomTemplateModel]:
    """Fork a Library template into a NEW template owned by ``owner_id``.

    The source may be the caller's own template OR a shared org template
    (:func:`get_owned_or_shared`); a foreign *private* template is never
    readable, so this returns None and the route 404s. The fork is always
    personal (``is_shared=False``): it gets a per-owner-unique key
    (``<key>-copy``, ``-copy-2`` …) and a ``"(copy)"`` display name, content
    otherwise copied verbatim. Persisted via :func:`create_for_owner`, so the
    fork passes the same schema + descriptive-mode validation as any new
    template.
    """
    src = await get_owned_or_shared(source_id, owner_id, db)
    if src is None:
        return None
    payload = json.loads(src.content)
    payload["key"] = await _unique_copy_key(src.key, owner_id, db)
    payload["display_name"] = _copy_display_name(src.display_name)
    return await create_for_owner(owner_id, payload, db, is_shared=False)


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
    await _flush_mapping_unique(db, template.key)
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


_COPY_SUFFIX = "-copy"


def _copy_display_name(name: str) -> str:
    """``"<name> (copy)"`` trimmed to the display-name column cap."""
    suffix = " (copy)"
    return f"{name[: _DISPLAY_NAME_MAX - len(suffix)]}{suffix}"


async def _unique_copy_key(
    base_key: str, owner_id: uuid.UUID, db: AsyncSession
) -> str:
    """A per-owner-unique fork key: ``<base>-copy``, ``<base>-copy-2`` …

    Each candidate is trimmed so ``<base><suffix>`` fits the 50-char key column,
    and checked against the owner's existing keys. Falls back to a random suffix
    in the (practically impossible) event 999 copies all collide.
    """
    for n in range(1, 1000):
        suffix = _COPY_SUFFIX if n == 1 else f"{_COPY_SUFFIX}-{n}"
        candidate = f"{base_key[: _KEY_MAX - len(suffix)]}{suffix}"
        if await _find_by_owner_and_key(owner_id, candidate, db) is None:
            return candidate
    return f"{base_key[: _KEY_MAX - 9]}-{uuid.uuid4().hex[:8]}"


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
