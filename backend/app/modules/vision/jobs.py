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
from datetime import timezone
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


# ── Stale-job reaping (VIS-07) ───────────────────────────────────────────
#
# Stage 2 runs as a detached `spawn_background_task`. If the worker recycles
# or a step hangs, the task dies before its `except → mark_failed` and the row
# is stranded `running` forever — the dashboard shows "Finishing visual
# enrichment…" indefinitely and `stage2-status` never resolves.
#
# Video-import jobs have had a watchdog, a startup sweep and a cancel route
# since #570/#571. Stage 2 had NONE of it, which is why sessions from
# 2026-07-20 and 2026-07-29 sat in "Visual enrichment running" for weeks with
# nothing to reap them. This mirrors `video_import.jobs` deliberately rather
# than inventing a second pattern — same budget, same lazy-reap-on-poll shape,
# same "returns True iff it transitioned" contract, so the two stay
# comparable.

#: Well beyond the Stage 2 < 5 min SLA (CLAUDE.md), so a healthy run is never
#: reaped. Matches the video-import budget for one number to reason about.
STALE_RUNNING_BUDGET_S = 900  # 15 minutes


async def fail_if_stale(db: AsyncSession, job: Stage2JobModel) -> bool:
    """Fail a job stuck ``running`` past the budget. True iff it transitioned.

    Idempotent: a no-op for any non-running job, or one without ``started_at``.
    Compares tz-aware to guard against a naive column value.
    """
    if job.status != JOB_RUNNING or job.started_at is None:
        return False
    now = utcnow()
    started = job.started_at
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if (now - started).total_seconds() < STALE_RUNNING_BUDGET_S:
        return False
    job.status = JOB_FAILED
    job.completed_at = utcnow()
    job.error_message = (
        f"Visual enrichment did not complete within "
        f"{STALE_RUNNING_BUDGET_S // 60} minutes and was marked failed."
    )
    await db.commit()
    logger.info("Reaped stale Stage 2 job: job=%s session=%s", job.id, job.session_id)
    return True


async def recover_orphaned_jobs(db: AsyncSession) -> list[uuid.UUID]:
    """Reap every Stage 2 job stranded ``running`` past the budget.

    Startup sweep: a container recycle kills the detached task before its
    in-process handler runs, and without this the row is only reachable by a
    status poll — which iOS stops making once the clinician moves on. Returns
    the session ids it failed so the caller can audit them.

    Budget-gated via :func:`fail_if_stale`, so a job legitimately running on
    another live replica (< budget) is left untouched.
    """
    result = await db.execute(
        select(Stage2JobModel).where(Stage2JobModel.status == JOB_RUNNING)
    )
    reaped: list[uuid.UUID] = []
    for job in result.scalars().all():
        if await fail_if_stale(db, job):
            reaped.append(job.session_id)
    return reaped
