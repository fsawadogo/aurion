"""VIS-07 — Stage 2 jobs must not strand in ``running`` forever.

Stage 2 is a detached ``spawn_background_task``. If the worker recycles or a
step hangs, the task dies before its ``except → mark_failed`` and the row stays
``running``: the dashboard shows "Finishing visual enrichment…" indefinitely
and ``stage2-status`` never resolves.

Video-import jobs have had a watchdog, a startup sweep and a cancel route since
#570/#571. Stage 2 had NONE of it — which is why four sessions were stuck when
this was written, two of them for over two weeks, with nothing in the system
able to reap them.

These mirror the video-import watchdog tests deliberately, so the two stay
comparable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.modules.vision.jobs import (
    JOB_COMPLETED,
    JOB_PENDING,
    JOB_RUNNING,
    STALE_RUNNING_BUDGET_S,
    fail_if_stale,
    recover_orphaned_jobs,
)


class _DB:
    """Minimal AsyncSession stand-in: records commits, returns canned rows."""

    def __init__(self, rows=None):
        self.commits = 0
        self._rows = rows or []

    async def commit(self):
        self.commits += 1

    async def execute(self, *_a, **_kw):
        rows = self._rows

        class _Result:
            def scalars(self):
                return SimpleNamespace(all=lambda: rows)

        return _Result()


def _job(status=JOB_RUNNING, age_s=None, started=True):
    started_at = None
    if started:
        age = age_s if age_s is not None else 0
        started_at = datetime.now(timezone.utc) - timedelta(seconds=age)
    return SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        status=status,
        started_at=started_at,
        completed_at=None,
        error_message=None,
        frames_processed=0,
    )


class TestFailIfStale:
    @pytest.mark.asyncio
    async def test_a_job_running_past_the_budget_is_failed(self):
        """The actual bug: a job stuck for hours, with nothing to reap it."""
        job = _job(age_s=STALE_RUNNING_BUDGET_S + 60)
        db = _DB()

        assert await fail_if_stale(db, job) is True
        assert job.status == "failed"
        assert job.completed_at is not None
        assert "did not complete" in job.error_message
        assert db.commits == 1

    @pytest.mark.asyncio
    async def test_a_healthy_run_inside_the_budget_is_untouched(self):
        """Stage 2's SLA is 5 min; the budget is 15. Never reap a live run."""
        job = _job(age_s=60)
        db = _DB()

        assert await fail_if_stale(db, job) is False
        assert job.status == JOB_RUNNING
        assert db.commits == 0

    @pytest.mark.asyncio
    async def test_a_terminal_job_is_never_touched(self):
        job = _job(status=JOB_COMPLETED, age_s=STALE_RUNNING_BUDGET_S + 60)
        db = _DB()

        assert await fail_if_stale(db, job) is False
        assert job.status == JOB_COMPLETED

    @pytest.mark.asyncio
    async def test_a_pending_job_is_never_touched(self):
        """Pending means dispatch hasn't happened; there is nothing to reap."""
        job = _job(status=JOB_PENDING, started=False)
        assert await fail_if_stale(_DB(), job) is False

    @pytest.mark.asyncio
    async def test_a_naive_started_at_does_not_explode(self):
        """The column can come back naive; comparing naive to aware raises."""
        job = _job(age_s=STALE_RUNNING_BUDGET_S + 60)
        job.started_at = job.started_at.replace(tzinfo=None)

        assert await fail_if_stale(_DB(), job) is True

    @pytest.mark.asyncio
    async def test_reaping_is_idempotent(self):
        """A second poll must not re-fail an already-failed job."""
        job = _job(age_s=STALE_RUNNING_BUDGET_S + 60)
        db = _DB()

        assert await fail_if_stale(db, job) is True
        assert await fail_if_stale(db, job) is False
        assert db.commits == 1


class TestStartupSweep:
    @pytest.mark.asyncio
    async def test_sweep_reaps_only_the_stale_ones(self):
        """The per-poll watchdog only fires while something polls, and iOS
        stops once the clinician moves on. The sweep is what clears a session
        nobody is looking at any more."""
        stale_a = _job(age_s=STALE_RUNNING_BUDGET_S + 3600)
        stale_b = _job(age_s=STALE_RUNNING_BUDGET_S + 86400)
        healthy = _job(age_s=30)
        db = _DB(rows=[stale_a, healthy, stale_b])

        reaped = await recover_orphaned_jobs(db)

        assert set(reaped) == {stale_a.session_id, stale_b.session_id}
        assert healthy.status == JOB_RUNNING, (
            "a job legitimately running on another replica was reaped"
        )

    @pytest.mark.asyncio
    async def test_sweep_with_nothing_stale_returns_empty(self):
        assert await recover_orphaned_jobs(_DB(rows=[_job(age_s=10)])) == []
