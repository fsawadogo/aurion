"""Async Stage 2 job tracking.

Vision enrichment used to run inline inside /approve-stage1, which blocked
the response until the model returned (up to the 5-min SLA). The async slice
moves it to a background task; this module records the job lifecycle so
iOS can poll status and the dashboard can show "Stage 2 in progress" tiles.

States: pending → running → completed | failed.
Each transition is persisted so a process restart doesn't lose status.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import Stage2JobModel

logger = logging.getLogger("aurion.vision.jobs")


# Public status literals — kept narrow on purpose. Anything else means the
# row was corrupted or written by an older codepath.
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
TERMINAL_STATES = frozenset({JOB_COMPLETED, JOB_FAILED})


async def create_job(session_id: uuid.UUID, db: AsyncSession) -> Stage2JobModel:
    """Create a fresh `pending` job row. Called synchronously inside
    /approve-stage1 before the background task is dispatched, so the
    job id is in the response."""
    job = Stage2JobModel(session_id=session_id, status=JOB_PENDING)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_latest_job(
    session_id: uuid.UUID, db: AsyncSession
) -> Optional[Stage2JobModel]:
    """Latest job for a session. iOS polls /stage2-status which calls this.
    Returns None if no Stage 2 was ever scheduled (session still in Stage 1)."""
    result = await db.execute(
        select(Stage2JobModel)
        .where(Stage2JobModel.session_id == session_id)
        .order_by(Stage2JobModel.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def mark_running(job_id: uuid.UUID, db: AsyncSession) -> None:
    job = await _load(job_id, db)
    if job is None or job.status != JOB_PENDING:
        return
    job.status = JOB_RUNNING
    job.started_at = utcnow()
    await db.commit()


async def mark_completed(
    job_id: uuid.UUID,
    *,
    new_note_version: int,
    frames_processed: int,
    db: AsyncSession,
) -> None:
    job = await _load(job_id, db)
    if job is None or job.status in TERMINAL_STATES:
        # Already terminal — don't clobber the original completion timestamp
        # or overwrite a failure with a stale completion signal.
        return
    job.status = JOB_COMPLETED
    job.completed_at = utcnow()
    job.new_note_version = new_note_version
    job.frames_processed = frames_processed
    await db.commit()


async def mark_failed(
    job_id: uuid.UUID,
    error_message: str,
    db: AsyncSession,
) -> None:
    job = await _load(job_id, db)
    if job is None or job.status in TERMINAL_STATES:
        return
    job.status = JOB_FAILED
    job.completed_at = utcnow()
    # Truncate so a runaway exception message can't bloat the row.
    job.error_message = error_message[:1000]
    await db.commit()


async def _load(job_id: uuid.UUID, db: AsyncSession) -> Optional[Stage2JobModel]:
    result = await db.execute(select(Stage2JobModel).where(Stage2JobModel.id == job_id))
    return result.scalar_one_or_none()
