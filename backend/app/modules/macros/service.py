"""CRUD service for `physician_macros` rows.

Owner-scoped throughout — every read path filters on `owner_id` and
every write path requires the caller's id be passed explicitly. The
service never reads or writes outside the caller's row set, so a
malicious or buggy route layer above can't accidentally leak across
clinicians.

Shortcut validation: must start with `/` and contain only ASCII
letters, digits, dashes, and underscores (1-32 chars after the slash).
This keeps the expansion trigger unambiguous (the leading `/` is the
flag) and avoids macros that look like ordinary clinical text.

Audit semantics: every create / update / delete writes an event with
the macro_id as the partition key + shortcut + actor_id; the body is
intentionally NOT recorded (macro bodies are physician-personal
phrasing; the audit log is the wrong place to store style fragments).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PhysicianMacroModel

logger = logging.getLogger("aurion.macros")

# Shortcut format guard. Leading slash + 1-32 chars of [a-zA-Z0-9_-]
# = ~63K possible 5-char shortcuts per physician (more than anyone
# will ever set). Stops free text like "patient's lung sounds clear"
# from accidentally becoming a shortcut.
_SHORTCUT_RE = re.compile(r"^/[a-zA-Z0-9_-]{1,32}$")


class MacroError(Exception):
    """Service-layer validation error. Route handlers map to 400/409."""


def _validate_shortcut(shortcut: str) -> str:
    """Normalise + validate a shortcut. Returns the cleaned value or
    raises MacroError with a human-readable message."""
    cleaned = shortcut.strip()
    if not _SHORTCUT_RE.match(cleaned):
        raise MacroError(
            "shortcut must start with '/' and contain only letters, "
            "digits, dashes, underscores (1-32 chars after the slash)"
        )
    return cleaned


def _validate_body(body: str) -> str:
    cleaned = body.strip()
    if not cleaned:
        raise MacroError("body must be non-empty")
    if len(cleaned) > 4096:
        raise MacroError("body exceeds 4096 chars")
    return cleaned


async def list_for_owner(
    owner_id: uuid.UUID,
    db: AsyncSession,
    specialty: Optional[str] = None,
) -> list[PhysicianMacroModel]:
    """List the caller's macros, optionally filtered to a specialty.

    Macros with `specialty IS NULL` are always returned regardless of
    the filter — they're the cross-specialty defaults; only specialty-
    scoped ones get filtered by the parameter.
    """
    stmt = select(PhysicianMacroModel).where(
        PhysicianMacroModel.owner_id == owner_id
    )
    if specialty:
        stmt = stmt.where(
            (PhysicianMacroModel.specialty == specialty)
            | (PhysicianMacroModel.specialty.is_(None))
        )
    stmt = stmt.order_by(PhysicianMacroModel.shortcut.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_owned(
    macro_id: uuid.UUID,
    owner_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[PhysicianMacroModel]:
    """Fetch a macro by id, scoped to the caller. None for non-owner
    or missing row (route layer maps both to 404 to avoid existence
    leaks)."""
    stmt = select(PhysicianMacroModel).where(
        PhysicianMacroModel.id == macro_id,
        PhysicianMacroModel.owner_id == owner_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_for_owner(
    owner_id: uuid.UUID,
    shortcut: str,
    body: str,
    db: AsyncSession,
    specialty: Optional[str] = None,
) -> PhysicianMacroModel:
    """Insert a new macro. Raises MacroError on validation; route layer
    maps to 400. Raises MacroError on uniqueness collision so the route
    layer can return 409 with a clear message."""
    clean_shortcut = _validate_shortcut(shortcut)
    clean_body = _validate_body(body)

    row = PhysicianMacroModel(
        id=uuid.uuid4(),
        owner_id=owner_id,
        shortcut=clean_shortcut,
        body=clean_body,
        specialty=specialty,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Unique constraint on (owner_id, shortcut). Re-surface as a
        # service-layer error with a stable message.
        await db.rollback()
        raise MacroError(
            f"Macro with shortcut '{clean_shortcut}' already exists"
        ) from exc
    return row


async def update_owned(
    row: PhysicianMacroModel,
    db: AsyncSession,
    shortcut: Optional[str] = None,
    body: Optional[str] = None,
    specialty: Optional[str] = None,
    clear_specialty: bool = False,
) -> PhysicianMacroModel:
    """Patch fields on an owned macro. Each kwarg is optional — only
    the fields the caller supplied are touched. `clear_specialty` flips
    the column back to null (you can't represent that via `specialty=None`
    here because that's already the no-change signal)."""
    if shortcut is not None:
        row.shortcut = _validate_shortcut(shortcut)
    if body is not None:
        row.body = _validate_body(body)
    if clear_specialty:
        row.specialty = None
    elif specialty is not None:
        row.specialty = specialty

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise MacroError(
            f"Another macro already uses shortcut '{row.shortcut}'"
        ) from exc
    return row


async def delete_owned(
    row: PhysicianMacroModel, db: AsyncSession
) -> None:
    """Hard delete. The audit log captures the deletion separately
    so the historical trail is preserved."""
    await db.delete(row)
    await db.flush()
