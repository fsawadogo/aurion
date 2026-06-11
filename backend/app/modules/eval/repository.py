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
from app.core.models import EvalAssignmentModel, EvalScoreModel
from app.core.uuids import to_uuid


async def get_score(
    db: AsyncSession, session_id: str | uuid.UUID
) -> EvalScoreModel | None:
    return await db.get(EvalScoreModel, to_uuid(session_id))


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
    # Spec-aligned fields — all optional, persisted only when provided.
    descriptive_mode_pass: bool | None = None,
    soap_section_scores: dict[str, int] | None = None,
    hallucination_count: int | None = None,
    discrepancies: list[str] | None = None,
    # Provider attribution (#74 / OV-1) — stamped by the route from the
    # scored note's latest version; nullable like the spec fields.
    provider_used: str | None = None,
    model_name: str | None = None,
) -> EvalScoreModel:
    """Insert or overwrite the canonical score for ``session_id``.

    Uses Postgres's ``INSERT ... ON CONFLICT (session_id) DO UPDATE`` so
    re-scoring is a single round-trip and atomic vs. concurrent writes.

    Spec-aligned columns added in migration 0004 are nullable — re-scoring
    a row that previously had values with a payload that omits them sets
    the columns back to NULL (the form is the source of truth, not the
    prior row). Callers that want to preserve prior values must read +
    re-send them.
    """
    sid = to_uuid(session_id)
    now = utcnow()
    values = dict(
        session_id=sid,
        transcript_accuracy=transcript_accuracy,
        citation_correctness=citation_correctness,
        descriptive_mode_compliance=descriptive_mode_compliance,
        overall=overall,
        notes=notes,
        scored_by=scored_by,
        scored_at=now,
        descriptive_mode_pass=descriptive_mode_pass,
        soap_section_scores=soap_section_scores,
        hallucination_count=hallucination_count,
        discrepancies=discrepancies,
        provider_used=provider_used,
        model_name=model_name,
    )
    update_set = {k: v for k, v in values.items() if k != "session_id"}
    stmt = pg_insert(EvalScoreModel).values(**values).on_conflict_do_update(
        index_elements=[EvalScoreModel.session_id],
        set_=update_set,
    )
    await db.execute(stmt)
    row = await db.get(EvalScoreModel, sid)
    assert row is not None  # we just upserted; impossible to be missing
    return row


# ── Assignments ────────────────────────────────────────────────────────────


async def get_assignment(
    db: AsyncSession, session_id: str | uuid.UUID
) -> EvalAssignmentModel | None:
    return await db.get(EvalAssignmentModel, to_uuid(session_id))


async def get_assignments_by_sessions(
    db: AsyncSession,
    session_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, EvalAssignmentModel]:
    """Batch-load assignment rows for a set of session ids."""
    ids = list(session_ids)
    if not ids:
        return {}
    stmt = select(EvalAssignmentModel).where(
        EvalAssignmentModel.session_id.in_(ids)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {row.session_id: row for row in rows}


async def get_session_ids_assigned_to(
    db: AsyncSession, assignee_user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Return the set of session ids currently assigned to this user."""
    stmt = select(EvalAssignmentModel.session_id).where(
        EvalAssignmentModel.assignee_user_id == assignee_user_id
    )
    rows = (await db.execute(stmt)).scalars().all()
    return set(rows)


async def upsert_assignment(
    db: AsyncSession,
    *,
    session_id: str | uuid.UUID,
    assignee_user_id: uuid.UUID,
    assignee_email: str,
    assigned_by: uuid.UUID,
    assigned_by_email: str,
) -> EvalAssignmentModel:
    """Insert or overwrite the canonical assignment for ``session_id``.

    Re-assigning resets ``completed_at`` to NULL so the new assignee
    sees the session in their queue.
    """
    sid = to_uuid(session_id)
    now = utcnow()
    values = dict(
        session_id=sid,
        assignee_user_id=assignee_user_id,
        assignee_email=assignee_email,
        assigned_by=assigned_by,
        assigned_by_email=assigned_by_email,
        assigned_at=now,
        completed_at=None,
    )
    update_set = {k: v for k, v in values.items() if k != "session_id"}
    stmt = pg_insert(EvalAssignmentModel).values(**values).on_conflict_do_update(
        index_elements=[EvalAssignmentModel.session_id],
        set_=update_set,
    )
    await db.execute(stmt)
    row = await db.get(EvalAssignmentModel, sid)
    assert row is not None
    return row


async def delete_assignment(
    db: AsyncSession, session_id: str | uuid.UUID
) -> bool:
    """Remove the assignment for ``session_id``. Returns True if a row
    was deleted, False if no assignment existed."""
    from sqlalchemy import delete as sa_delete

    sid = to_uuid(session_id)
    stmt = sa_delete(EvalAssignmentModel).where(
        EvalAssignmentModel.session_id == sid
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def mark_assignment_complete(
    db: AsyncSession, session_id: str | uuid.UUID
) -> EvalAssignmentModel | None:
    """Set ``completed_at = now`` on the assignment for ``session_id``
    if one exists. Called when the assignee submits a score."""
    sid = to_uuid(session_id)
    row = await db.get(EvalAssignmentModel, sid)
    if row is None:
        return None
    row.completed_at = utcnow()
    await db.flush()
    return row
