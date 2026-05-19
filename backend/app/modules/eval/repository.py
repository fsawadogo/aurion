"""Database-access helpers for ``EvalScoreModel``.

Mirrors ``note_gen/repository.py`` and ``auth/users_repository.py``:
small focused queries the admin/eval endpoints consume in place of the
prior in-memory ``_EVAL_SCORES`` dict.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import EvalScoreModel


def _to_uuid(session_id: str | uuid.UUID) -> uuid.UUID:
    return session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))


async def get_score(
    db: AsyncSession, session_id: str | uuid.UUID
) -> EvalScoreModel | None:
    return await db.get(EvalScoreModel, _to_uuid(session_id))


async def get_scores_by_sessions(
    db: AsyncSession,
    session_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, EvalScoreModel]:
    """Batch-load scores for a set of session ids.

    Single query — keeps the eval list endpoint from doing N round-trips.
    Sessions with no score are absent from the dict.
    """
    ids = list(session_ids)
    if not ids:
        return {}
    stmt = select(EvalScoreModel).where(EvalScoreModel.session_id.in_(ids))
    rows = (await db.execute(stmt)).scalars().all()
    return {row.session_id: row for row in rows}


async def upsert_score(
    db: AsyncSession,
    *,
    session_id: str | uuid.UUID,
    transcript_accuracy: float,
    citation_correctness: float,
    descriptive_mode_compliance: float,
    overall: float,
    notes: str,
    scored_by: str,
) -> EvalScoreModel:
    """Insert or overwrite the canonical score for ``session_id``.

    Uses Postgres's ``INSERT ... ON CONFLICT (session_id) DO UPDATE`` so
    re-scoring is a single round-trip and atomic vs. concurrent writes.
    """
    sid = _to_uuid(session_id)
    now = utcnow()
    stmt = pg_insert(EvalScoreModel).values(
        session_id=sid,
        transcript_accuracy=transcript_accuracy,
        citation_correctness=citation_correctness,
        descriptive_mode_compliance=descriptive_mode_compliance,
        overall=overall,
        notes=notes,
        scored_by=scored_by,
        scored_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[EvalScoreModel.session_id],
        set_=dict(
            transcript_accuracy=transcript_accuracy,
            citation_correctness=citation_correctness,
            descriptive_mode_compliance=descriptive_mode_compliance,
            overall=overall,
            notes=notes,
            scored_by=scored_by,
            scored_at=now,
        ),
    )
    await db.execute(stmt)
    # Refetch so the caller gets the persisted row (including server-side
    # values if any get added later).
    row = await db.get(EvalScoreModel, sid)
    assert row is not None  # we just upserted; impossible to be missing
    return row
