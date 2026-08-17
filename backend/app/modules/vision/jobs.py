"""Async Stage 2 job tracking.

Vision enrichment used to run inline inside /approve-stage1, which blocked
the response until the model returned (up to the 5-min SLA). The async slice
moves it to a background task; this module records the job lifecycle so
iOS can poll status and the dashboard can show "Stage 2 in progress" tiles.

States: pending → running → completed | failed.
Each transition is persisted so a process restart doesn't lose status.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timezone
from typing import Awaitable, Optional, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import Stage2JobModel
from app.modules.config.appconfig_client import get_config

logger = logging.getLogger("aurion.vision.jobs")

_T = TypeVar("_T")


# Public status literals — kept narrow on purpose. Anything else means the
# row was corrupted or written by an older codepath.
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
TERMINAL_STATES = frozenset({JOB_COMPLETED, JOB_FAILED})

# Persisted/public failure values are deliberately codes, never exception
# messages. Provider/model exceptions can contain transcript or generated-note
# text, so carrying ``str(exc)`` into the job row would also leak it through the
# clinician-facing status endpoint.
STAGE2_FAILURE_REASON = "stage2_processing_failed"
STAGE2_DEADLINE_REASON = "stage2_deadline_exceeded"
STAGE2_ORPHAN_REAP_REASON = "stage2_orphan_reaped"
_PUBLIC_FAILURE_REASONS = frozenset(
    {
        STAGE2_FAILURE_REASON,
        STAGE2_DEADLINE_REASON,
        STAGE2_ORPHAN_REAP_REASON,
    }
)


async def create_job(session_id: uuid.UUID, db: AsyncSession) -> Stage2JobModel:
    """Create a fresh `pending` job row. Called synchronously inside
    /approve-stage1 before the background task is dispatched, so the
    job id is in the response."""
    job = Stage2JobModel(session_id=session_id, status=JOB_PENDING)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_latest_job(session_id: uuid.UUID, db: AsyncSession) -> Optional[Stage2JobModel]:
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
) -> bool:
    """Atomically complete a running job; return whether this owner won.

    The conditional update is the terminal ownership decision. A stale task
    cannot overwrite a watchdog/provider failure that committed first. The
    caller must roll back its pending note version when ``False`` is returned;
    on success the job row and that note version commit together.
    """
    result = await db.execute(
        update(Stage2JobModel)
        .where(
            Stage2JobModel.id == job_id,
            Stage2JobModel.status == JOB_RUNNING,
        )
        .values(
            status=JOB_COMPLETED,
            completed_at=utcnow(),
            new_note_version=new_note_version,
            frames_processed=frames_processed,
            error_message=None,
        )
        .returning(Stage2JobModel.id)
    )
    transitioned = result.scalar_one_or_none() is not None
    if transitioned:
        await db.commit()
    return transitioned


async def mark_failed(
    job_id: uuid.UUID,
    error_message: str,
    db: AsyncSession,
) -> bool:
    """Atomically fail a non-terminal job; return whether this owner won.

    ``error_message`` is normalized to the small public reason-code set so a
    future caller cannot accidentally persist provider/model text.
    """
    reason = public_stage2_failure_reason(error_message) or STAGE2_FAILURE_REASON
    result = await db.execute(
        update(Stage2JobModel)
        .where(
            Stage2JobModel.id == job_id,
            Stage2JobModel.status.in_((JOB_PENDING, JOB_RUNNING)),
        )
        .values(
            status=JOB_FAILED,
            completed_at=utcnow(),
            error_message=reason,
        )
        .returning(Stage2JobModel.id)
    )
    transitioned = result.scalar_one_or_none() is not None
    if transitioned:
        await db.commit()
    return transitioned


async def _load(job_id: uuid.UUID, db: AsyncSession) -> Optional[Stage2JobModel]:
    result = await db.execute(select(Stage2JobModel).where(Stage2JobModel.id == job_id))
    return result.scalar_one_or_none()


def public_stage2_failure_reason(reason: Optional[str]) -> Optional[str]:
    """Return only approved reason codes, hiding legacy raw DB messages."""
    if reason is None:
        return None
    if reason in _PUBLIC_FAILURE_REASONS:
        return reason
    return STAGE2_FAILURE_REASON


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

# A live owner must stop its work before the database-only orphan reaper fires.
# The configured Stage 2 SLA is normally five minutes; this guard only matters
# if an operator raises that SLA beyond the stale-row budget. Keeping a small
# margin makes ownership deterministic: the task cancels its awaited caption
# fan-out and records failure, while the 15-minute reaper remains a fallback for
# a dead worker that can no longer execute its own timeout handler.
_ORPHAN_REAPER_GRACE_S = 30


class Stage2DeadlineExceededError(TimeoutError):
    """The owner cancelled Stage 2 after its configured runtime budget."""


def stage2_failure_reason(exc: BaseException) -> str:
    """Map an exception to a stable, PHI-free persisted/audited reason."""
    if isinstance(exc, Stage2DeadlineExceededError):
        return STAGE2_DEADLINE_REASON
    return STAGE2_FAILURE_REASON


def stage2_hard_deadline_seconds() -> float:
    """Return the config-driven Stage 2 deadline, bounded below the reaper."""
    configured_seconds = get_config().alerting.sla_stage2_ms / 1000.0
    owner_ceiling = float(STALE_RUNNING_BUDGET_S - _ORPHAN_REAPER_GRACE_S)
    if configured_seconds > owner_ceiling:
        logger.warning(
            "Configured Stage 2 SLA %.1fs exceeds the owner-safe ceiling %.1fs; clamping below the orphan reaper",
            configured_seconds,
            owner_ceiling,
        )
    return min(configured_seconds, owner_ceiling)


async def run_with_stage2_deadline(operation: Awaitable[_T]) -> _T:
    """Await one complete Stage 2 run under its owner-enforced hard deadline.

    ``asyncio.timeout`` cancels the current awaited chain when it expires. In
    Stage 2 that cancellation reaches ``caption_visual_evidence``'s gather,
    every active provider request/retry sleep, and every item still queued on
    the caption semaphore. The context converts only *its own* cancellation to
    :class:`Stage2DeadlineExceededError`; an ECS shutdown cancellation remains
    ``CancelledError`` and continues propagating.
    """
    deadline_seconds = stage2_hard_deadline_seconds()
    timeout = asyncio.timeout(deadline_seconds)
    try:
        async with timeout:
            return await operation
    except TimeoutError as exc:
        # Preserve a TimeoutError raised by Stage 2 itself. Only translate the
        # timeout context's own expiry into the stable orchestration error.
        if not timeout.expired():
            raise
        raise Stage2DeadlineExceededError(
            f"Stage 2 exceeded its configured {deadline_seconds:.1f}s hard deadline."
        ) from exc


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
    transitioned = await mark_failed(job.id, STAGE2_ORPHAN_REAP_REASON, db)
    if not transitioned:
        return False
    # Refresh so callers can serialize the same ORM instance after the bulk
    # conditional update made the terminal ownership decision.
    await db.refresh(job)
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
    result = await db.execute(select(Stage2JobModel).where(Stage2JobModel.status == JOB_RUNNING))
    reaped: list[uuid.UUID] = []
    for job in result.scalars().all():
        if await fail_if_stale(db, job):
            reaped.append(job.session_id)
    return reaped
