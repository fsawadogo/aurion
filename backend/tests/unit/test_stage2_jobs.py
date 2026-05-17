"""M-07 / B-06: Stage 2 background job state machine.

Validates the pending → running → completed/failed transitions, and that
terminal states are non-clobberable (a stale completion can't overwrite a
recorded failure). Mocks the SQLAlchemy session — the jobs module is pure
state-machine logic on top of a single row.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import Stage2JobModel
from app.modules.vision.jobs import (
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    create_job,
    get_latest_job,
    mark_completed,
    mark_failed,
    mark_running,
)


def _mock_db_with(*, scalar_result=None) -> AsyncMock:
    """Async session mock with execute/commit/add/refresh.

    `scalar_result` is what `db.execute(...).scalar_one_or_none()` returns
    on EVERY call. This is enough for the jobs module because each helper
    issues exactly one SELECT before mutating + committing.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_create_job_starts_pending():
    db = _mock_db_with()
    job = await create_job(uuid.uuid4(), db)
    assert job.status == JOB_PENDING
    assert job.started_at is None
    assert job.completed_at is None
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_running_transition_records_started_at():
    existing = Stage2JobModel(id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_PENDING)
    db = _mock_db_with(scalar_result=existing)

    await mark_running(existing.id, db)

    assert existing.status == JOB_RUNNING
    assert existing.started_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_running_noop_when_not_pending():
    # Already-running jobs shouldn't bounce back to running and reset the
    # timer — that'd lie about when work started.
    existing = Stage2JobModel(
        id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING
    )
    db = _mock_db_with(scalar_result=existing)

    await mark_running(existing.id, db)

    assert existing.status == JOB_RUNNING
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_transition_persists_new_version():
    existing = Stage2JobModel(
        id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING
    )
    db = _mock_db_with(scalar_result=existing)

    await mark_completed(existing.id, new_note_version=3, frames_processed=12, db=db)

    assert existing.status == JOB_COMPLETED
    assert existing.new_note_version == 3
    assert existing.frames_processed == 12
    assert existing.completed_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_transition_truncates_long_errors():
    existing = Stage2JobModel(
        id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING
    )
    db = _mock_db_with(scalar_result=existing)
    long_error = "vision provider exploded: " + ("x" * 5000)

    await mark_failed(existing.id, long_error, db)

    assert existing.status == JOB_FAILED
    assert existing.error_message is not None
    assert len(existing.error_message) <= 1000


@pytest.mark.asyncio
async def test_completed_does_not_clobber_failed():
    # A late completion arriving after the job already errored must NOT
    # overwrite the failure — the original outcome is the canonical truth.
    existing = Stage2JobModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        status=JOB_FAILED,
        error_message="provider unavailable",
    )
    db = _mock_db_with(scalar_result=existing)

    await mark_completed(existing.id, new_note_version=2, frames_processed=4, db=db)

    assert existing.status == JOB_FAILED
    assert existing.new_note_version is None
    assert existing.error_message == "provider unavailable"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_latest_job_returns_row_when_present():
    job = Stage2JobModel(id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING)
    db = _mock_db_with(scalar_result=job)

    latest = await get_latest_job(job.session_id, db)
    assert latest is job


@pytest.mark.asyncio
async def test_get_latest_job_none_when_no_jobs():
    db = _mock_db_with(scalar_result=None)
    latest = await get_latest_job(uuid.uuid4(), db)
    assert latest is None
