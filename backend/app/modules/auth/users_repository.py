"""Database-access helpers for ``UserModel``.

Mirrors the ``note_gen/repository.py`` pattern — small, focused queries
the admin endpoints (and ``_get_clinician_name`` lookups) consume in
place of in-memory dicts.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import UserModel
from app.core.types import UserRole
from app.core.uuids import to_uuid


async def list_users(db: AsyncSession) -> list[UserModel]:
    """Return all users, deterministic order (created_at ascending)."""
    stmt = select(UserModel).order_by(UserModel.created_at.asc())
    return list((await db.execute(stmt)).scalars().all())


async def get_user(
    db: AsyncSession, user_id: str | uuid.UUID
) -> UserModel | None:
    return await db.get(UserModel, to_uuid(user_id))


async def get_by_email(
    db: AsyncSession, email: str
) -> UserModel | None:
    """Look up a user by their email. Case-sensitive — Cognito + the
    admin user pool both treat email as the canonical identifier."""
    stmt = select(UserModel).where(UserModel.email == email)
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    full_name: str,
    role: UserRole,
    password_hash: str,
    voice_enrolled: bool = False,
) -> UserModel:
    """Insert a new user. Caller hashes the password (passwords module).

    Email collisions are caught by the unique constraint on ``users.email``
    and surface as ``sqlalchemy.exc.IntegrityError`` — the caller maps
    that to HTTP 409.
    """
    user = UserModel(
        email=email.lower(),
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        voice_enrolled=voice_enrolled,
    )
    db.add(user)
    await db.flush()
    return user


async def update_user(
    db: AsyncSession,
    user_id: str | uuid.UUID,
    *,
    full_name: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    mfa_required: bool | None = None,
    prompt_testing_enabled: bool | None = None,
) -> tuple[UserModel, dict[str, Any]] | None:
    """Apply a partial update and return ``(user, changes)``.

    ``changes`` is a {field: {previous, new}} dict suitable for the
    ``user_updated`` audit event. ``None`` is returned if the user
    doesn't exist; the caller raises 404.
    """
    user = await get_user(db, user_id)
    if user is None:
        return None

    changes: dict[str, Any] = {}
    if full_name is not None and full_name != user.full_name:
        changes["full_name"] = {"previous": user.full_name, "new": full_name}
        user.full_name = full_name
    if role is not None and role != user.role:
        changes["role"] = {"previous": user.role.value, "new": role.value}
        user.role = role
    if is_active is not None and is_active != user.is_active:
        changes["is_active"] = {"previous": user.is_active, "new": is_active}
        user.is_active = is_active
    if mfa_required is not None and mfa_required != user.mfa_required:
        changes["mfa_required"] = {"previous": user.mfa_required, "new": mfa_required}
        user.mfa_required = mfa_required
    if (
        prompt_testing_enabled is not None
        and prompt_testing_enabled != user.prompt_testing_enabled
    ):
        changes["prompt_testing_enabled"] = {
            "previous": user.prompt_testing_enabled,
            "new": prompt_testing_enabled,
        }
        user.prompt_testing_enabled = prompt_testing_enabled

    if changes:
        await db.flush()
    return user, changes


async def get_clinician_names(
    db: AsyncSession,
    clinician_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Batch-load full_name for a set of clinician ids.

    Returns ``{id: full_name}``; unknown ids are absent so callers can
    fall back to the short-uuid label.
    """
    ids = list(clinician_ids)
    if not ids:
        return {}
    stmt = select(UserModel.id, UserModel.full_name).where(UserModel.id.in_(ids))
    rows = (await db.execute(stmt)).all()
    return {row.id: row.full_name for row in rows}
