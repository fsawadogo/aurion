"""Persistence helpers for video-import jobs (VID-01).

Thin CRUD over ``VideoImportJobModel`` mirroring the Stage 2 job lifecycle
(pending → running → completed|failed). No business logic — the orchestrator
(later slice) owns sequencing; these just move the row through its states so
the portal can poll progress and an operator can recover a stuck job.
"""

from __future__ import annotations

import uuid
from datetime import timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import VideoImportJobModel


async def create_job(
    db: AsyncSession,
    session_id: uuid.UUID,
    raw_video_s3_key: str,
    auto_advance_stage2: bool = False,
) -> VideoImportJobModel:
    """Create a pending video-import job for a session."""
    job = VideoImportJobModel(
        session_id=session_id,
        status="pending",
        raw_video_s3_key=raw_video_s3_key,
        auto_advance_stage2=auto_advance_stage2,
    )
    db.add(job)
    await db.commit()
    return job


async def get_job(
    db: AsyncSession, job_id: uuid.UUID
) -> Optional[VideoImportJobModel]:
    """Fetch a job by id."""
    result = await db.execute(
        select(VideoImportJobModel).where(VideoImportJobModel.id == job_id)
    )
    return result.scalar_one_or_none()


async def get_job_for_session(
    db: AsyncSession, session_id: uuid.UUID
) -> Optional[VideoImportJobModel]:
    """Fetch the most recently created job for a session."""
    result = await db.execute(
        select(VideoImportJobModel)
        .where(VideoImportJobModel.session_id == session_id)
        .order_by(VideoImportJobModel.created_at.desc())
    )
    return result.scalars().first()


async def mark_running(
    db: AsyncSession, job: VideoImportJobModel
) -> VideoImportJobModel:
    """Transition a job to running, stamping ``started_at``."""
    job.status = "running"
    job.started_at = utcnow()
    await db.commit()
    return job


async def mark_completed(
    db: AsyncSession,
    job: VideoImportJobModel,
    *,
    frames_extracted: int = 0,
    frames_masked: int = 0,
    frames_dropped: int = 0,
    new_note_version: Optional[int] = None,
) -> VideoImportJobModel:
    """Transition a job to completed, recording frame counters + result."""
    job.status = "completed"
    job.completed_at = utcnow()
    job.frames_extracted = frames_extracted
    job.frames_masked = frames_masked
    job.frames_dropped = frames_dropped
    job.new_note_version = new_note_version
    await db.commit()
    return job


async def mark_failed(
    db: AsyncSession,
    job: VideoImportJobModel,
    reason: str,
) -> VideoImportJobModel:
    """Transition a job to failed with a bounded, PHI-free reason."""
    job.status = "failed"
    job.completed_at = utcnow()
    job.error_message = reason[:500]
    await db.commit()
    return job


async def mark_raw_video_purged(
    db: AsyncSession, job: VideoImportJobModel
) -> VideoImportJobModel:
    """Stamp ``raw_video_purged_at`` once the uploaded video is deleted."""
    job.raw_video_purged_at = utcnow()
    await db.commit()
    return job


# Lazy-watchdog budget. The orchestrator is a fire-and-forget
# ``asyncio.create_task`` — if its worker recycles or a step (e.g. ffmpeg)
# hangs, the task dies before its ``except → mark_failed`` and the row is
# stranded in ``running``, so the portal poll spins forever. This budget is far
# beyond the Stage 1 (<30s) + Stage 2 (<5min) SLAs (CLAUDE.md), so a healthy
# run is never reaped.
STALE_RUNNING_BUDGET_S = 900  # 15 minutes


async def fail_if_stale(db: AsyncSession, job: VideoImportJobModel) -> bool:
    """Fail a job stuck ``running`` past ``STALE_RUNNING_BUDGET_S``.

    Called on every status poll so a stranded job (dead/hung orchestrator task)
    surfaces as ``failed`` — which the portal already renders + which makes the
    job re-runnable via ``/process`` — instead of an infinite spinner. Returns
    True iff it transitioned the job. Idempotent: a no-op for any non-running
    job, or one without ``started_at``. Compares tz-aware to guard against a
    naive column value.
    """
    if job.status != "running" or job.started_at is None:
        return False
    now = utcnow()
    started = job.started_at
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if (now - started).total_seconds() < STALE_RUNNING_BUDGET_S:
        return False
    await mark_failed(
        db,
        job,
        f"Processing did not complete within {STALE_RUNNING_BUDGET_S // 60} "
        "minutes and was marked failed. Re-run the import to try again.",
    )
    return True
