"""Unit tests for the video-import stale-job watchdog (vid-fix-stuck-import).

The orchestrator is a fire-and-forget ``asyncio.create_task``; if its worker
recycles or a step hangs, the task dies before its ``except -> mark_failed`` and
the job is stranded in "running", so the portal poll spins forever. The lazy
watchdog fails such a job on the next status poll so the UI surfaces an error
(and the job becomes re-runnable) instead of an infinite spinner.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1 import video_import as vi
from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.modules.video_import import jobs

_STALE = jobs.STALE_RUNNING_BUDGET_S + 60


def _job(**over):
    base = dict(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        status="running",
        started_at=utcnow() - timedelta(seconds=_STALE),
        completed_at=None,
        error_message=None,
        frames_extracted=0,
        frames_masked=0,
        frames_dropped=0,
        new_note_version=None,
        raw_video_s3_key="vid/x.mp4",
        raw_video_purged_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ── fail_if_stale (jobs service) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_if_stale_fails_stuck_running_job() -> None:
    db = AsyncMock()
    job = _job()
    assert await jobs.fail_if_stale(db, job) is True
    assert job.status == "failed"
    assert job.error_message and "did not complete" in job.error_message
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_fail_if_stale_leaves_fresh_running_job() -> None:
    db = AsyncMock()
    job = _job(started_at=utcnow() - timedelta(seconds=10))
    assert await jobs.fail_if_stale(db, job) is False
    assert job.status == "running"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "completed", "failed"])
async def test_fail_if_stale_noop_for_non_running(status: str) -> None:
    db = AsyncMock()
    job = _job(status=status)
    assert await jobs.fail_if_stale(db, job) is False
    assert job.status == status
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_fail_if_stale_handles_naive_started_at() -> None:
    """A naive (tz-less) column value must not crash the comparison."""
    db = AsyncMock()
    naive = (utcnow() - timedelta(seconds=_STALE)).replace(tzinfo=None)
    job = _job(started_at=naive)
    assert await jobs.fail_if_stale(db, job) is True
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_fail_if_stale_noop_without_started_at() -> None:
    db = AsyncMock()
    job = _job(started_at=None)
    assert await jobs.fail_if_stale(db, job) is False


# ── status route applies the watchdog ────────────────────────────────────


@pytest.mark.asyncio
async def test_status_route_reaps_stale_job_and_audits() -> None:
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    session = SimpleNamespace(
        id=uuid.uuid4(), state=SimpleNamespace(value="PROCESSING_STAGE1")
    )
    job = _job()
    with patch.object(
        vi, "get_owned_session_or_404", AsyncMock(return_value=session)
    ), patch.object(
        vi.jobs, "get_job_for_session", AsyncMock(return_value=job)
    ), patch.object(vi, "write_audit", AsyncMock()) as audit:
        resp = await vi.get_video_import_status(session.id, None, user, db)

    assert job.status == "failed"
    assert resp.status == "failed"
    # The auto-failure is recorded as VIDEO_IMPORT_FAILED (event is arg[1]).
    assert audit.await_args.args[1] == AuditEventType.VIDEO_IMPORT_FAILED


@pytest.mark.asyncio
async def test_status_route_leaves_healthy_job_untouched() -> None:
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    session = SimpleNamespace(
        id=uuid.uuid4(), state=SimpleNamespace(value="PROCESSING_STAGE1")
    )
    job = _job(started_at=utcnow() - timedelta(seconds=5))
    with patch.object(
        vi, "get_owned_session_or_404", AsyncMock(return_value=session)
    ), patch.object(
        vi.jobs, "get_job_for_session", AsyncMock(return_value=job)
    ), patch.object(vi, "write_audit", AsyncMock()) as audit:
        resp = await vi.get_video_import_status(session.id, None, user, db)

    assert resp.status == "running"
    audit.assert_not_awaited()
