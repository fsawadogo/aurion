"""Database-access helpers for note versions.

Pulls the ``select(NoteVersionModel)...order_by(version.desc())`` query
out of ``service.py`` (where it was repeated 4 times) and out of admin
/ privacy routes (2 more occurrences). Service-level code can still
``_deserialize`` the row into a ``Note``; this module only owns the
row-fetching.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import NoteVersionModel


def _to_uuid(session_id: str | uuid.UUID) -> uuid.UUID:
    return session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))


async def get_latest_version(
    db: AsyncSession,
    session_id: str | uuid.UUID,
    *,
    stage: Optional[int] = None,
) -> Optional[NoteVersionModel]:
    """Return the highest-version row for ``session_id``, or None.

    When ``stage`` is set, only versions at that pipeline stage are
    considered — used by callers that need "the latest Stage 1 note"
    distinct from "the latest of any stage".
    """
    stmt = select(NoteVersionModel).where(NoteVersionModel.session_id == _to_uuid(session_id))
    if stage is not None:
        stmt = stmt.where(NoteVersionModel.stage == stage)
    stmt = stmt.order_by(NoteVersionModel.version.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_all_versions(
    db: AsyncSession,
    session_id: str | uuid.UUID,
) -> list[NoteVersionModel]:
    """Return every version row for ``session_id``, ascending by version."""
    stmt = (
        select(NoteVersionModel)
        .where(NoteVersionModel.session_id == _to_uuid(session_id))
        .order_by(NoteVersionModel.version.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_latest_versions_by_session(
    db: AsyncSession,
    session_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, NoteVersionModel]:
    """Batch-load the highest-version row for each session id.

    Single query — avoids N+1 in admin/eval list endpoints. Returns a
    dict keyed by session_id; sessions with no versions are absent.
    """
    ids = list(session_ids)
    if not ids:
        return {}

    max_version_sub = (
        select(
            NoteVersionModel.session_id,
            func.max(NoteVersionModel.version).label("max_ver"),
        )
        .where(NoteVersionModel.session_id.in_(ids))
        .group_by(NoteVersionModel.session_id)
        .subquery()
    )
    stmt = select(NoteVersionModel).join(
        max_version_sub,
        (NoteVersionModel.session_id == max_version_sub.c.session_id)
        & (NoteVersionModel.version == max_version_sub.c.max_ver),
    )
    result = await db.execute(stmt)
    return {nv.session_id: nv for nv in result.scalars().all()}
