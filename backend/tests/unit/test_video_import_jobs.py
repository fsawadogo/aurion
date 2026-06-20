"""VID-01 — video-import job lifecycle helpers.

Stubbed AsyncSession (no live DB) — same posture as
``test_custom_templates_service``. We assert the helpers move the
``VideoImportJobModel`` row through pending → running → completed/failed and
stamp the right fields; persistence itself is SQLAlchemy's job, exercised by
the integration suite.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.video_import import jobs


def _db() -> MagicMock:
    # SQLAlchemy's session.add is synchronous; flush is awaited.
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_job_starts_pending() -> None:
    db = _db()
    sid = uuid.uuid4()
    job = await jobs.create_job(
        db, sid, raw_video_s3_key=f"video-imports/{sid}/abc.mp4"
    )
    assert job.status == "pending"
    assert job.session_id == sid
    assert job.raw_video_s3_key == f"video-imports/{sid}/abc.mp4"
    assert job.auto_advance_stage2 is False
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_mark_running_stamps_started_at() -> None:
    db = _db()
    job = await jobs.create_job(db, uuid.uuid4(), raw_video_s3_key="k")
    await jobs.mark_running(db, job)
    assert job.status == "running"
    assert job.started_at is not None


@pytest.mark.asyncio
async def test_mark_completed_records_counts() -> None:
    db = _db()
    job = await jobs.create_job(db, uuid.uuid4(), raw_video_s3_key="k")
    await jobs.mark_completed(
        db, job, frames_extracted=12, frames_masked=9, frames_dropped=3,
        new_note_version=2,
    )
    assert job.status == "completed"
    assert job.completed_at is not None
    assert (job.frames_extracted, job.frames_masked, job.frames_dropped) == (12, 9, 3)
    assert job.new_note_version == 2


@pytest.mark.asyncio
async def test_mark_failed_truncates_reason() -> None:
    db = _db()
    job = await jobs.create_job(db, uuid.uuid4(), raw_video_s3_key="k")
    await jobs.mark_failed(db, job, reason="x" * 1000)
    assert job.status == "failed"
    assert job.error_message is not None
    assert len(job.error_message) == 500


@pytest.mark.asyncio
async def test_mark_raw_video_purged_stamps_timestamp() -> None:
    db = _db()
    job = await jobs.create_job(db, uuid.uuid4(), raw_video_s3_key="k")
    assert job.raw_video_purged_at is None
    await jobs.mark_raw_video_purged(db, job)
    assert job.raw_video_purged_at is not None
