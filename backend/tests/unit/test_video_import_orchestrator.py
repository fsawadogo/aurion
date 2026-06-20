"""VID-02 — the background orchestrator's contract (mocked; no DB/S3/ffmpeg).

Locks the invariants that matter for safety + correctness:
  * happy path: download → extract → PURGE raw video → drive
    RECORDING→PROCESSING_STAGE1 → run_stage1 → mark_completed +
    VIDEO_IMPORT_COMPLETE.
  * FAIL-CLOSED: the raw uploaded video is purged exactly once whether
    Stage 1 succeeds, Stage 1 fails (purge already done in the main path),
    or extraction fails before the purge (best-effort purge in the handler).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import video_import as vi
from app.core.audit_events import AuditEventType
from app.core.types import SessionState


class _FakeSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_a):
        return False


def _job() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw_video_s3_key=f"video-imports/{uuid.uuid4()}/v.mp4",
        raw_video_purged_at=None,
        status="running",
    )


def _session() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), state=SessionState.CONSENT_PENDING)


def _patches(job, session, *, extract=None, stage1=None, purge=None):
    """Common patch set for the orchestrator. Returns a contextlib stack-like
    list of patchers already started; caller stops them."""

    async def _fake_extract(video_path, wav_path):
        with open(wav_path, "wb") as fh:
            fh.write(b"RIFFfakewav")
        return wav_path

    async def _mark_purged(db, j):
        j.raw_video_purged_at = object()
        return j

    db = AsyncMock()
    client = MagicMock()
    client.download_file = MagicMock(return_value=None)

    started = [
        patch.object(vi, "async_session_factory", lambda: _FakeSessionCtx(db)),
        patch.object(vi.jobs, "get_job", AsyncMock(return_value=job)),
        patch.object(vi, "get_session", AsyncMock(return_value=session)),
        patch.object(vi.jobs, "mark_running", AsyncMock()),
        patch.object(vi.jobs, "mark_completed", AsyncMock()),
        patch.object(vi.jobs, "mark_failed", AsyncMock()),
        patch.object(vi.jobs, "mark_raw_video_purged", AsyncMock(side_effect=_mark_purged)),
        patch.object(vi, "get_s3_client", MagicMock(return_value=client)),
        patch.object(vi, "extract_audio", AsyncMock(side_effect=extract or _fake_extract)),
        patch.object(vi, "transition_session", AsyncMock()),
        patch.object(vi, "write_audit", AsyncMock()),
        patch.object(vi, "run_stage1", AsyncMock(side_effect=stage1)),
        patch.object(vi, "purge_raw_video", AsyncMock(side_effect=purge)),
        patch.object(vi, "try_publish_alert", AsyncMock()),
    ]
    for p in started:
        p.start()
    return started


def _stop(started):
    for p in started:
        p.stop()


@pytest.mark.asyncio
async def test_happy_path_purges_and_completes() -> None:
    job, session = _job(), _session()
    started = _patches(job, session)
    try:
        await vi._run_video_import_in_background(session.id, job.id)
        assert vi.purge_raw_video.await_count == 1
        vi.purge_raw_video.assert_awaited_with(str(session.id), job.raw_video_s3_key)
        vi.run_stage1.assert_awaited_once()
        vi.jobs.mark_completed.assert_awaited_once()
        # Drove RECORDING then PROCESSING_STAGE1.
        states = [c.args[2] for c in vi.transition_session.await_args_list]
        assert states == [SessionState.RECORDING, SessionState.PROCESSING_STAGE1]
        events = [c.args[1] for c in vi.write_audit.await_args_list]
        assert AuditEventType.VIDEO_IMPORT_COMPLETE in events
    finally:
        _stop(started)


@pytest.mark.asyncio
async def test_stage1_failure_still_purged_once_and_marked_failed() -> None:
    job, session = _job(), _session()

    async def _boom(*_a, **_k):
        raise RuntimeError("stage1 blew up")

    started = _patches(job, session, stage1=_boom)
    try:
        await vi._run_video_import_in_background(session.id, job.id)
        # Purge happened in the main path (step 2) and is NOT repeated
        # (raw_video_purged_at was stamped) — exactly once.
        assert vi.purge_raw_video.await_count == 1
        vi.jobs.mark_failed.assert_awaited_once()
        events = [c.args[1] for c in vi.write_audit.await_args_list]
        assert AuditEventType.VIDEO_IMPORT_FAILED in events
        vi.try_publish_alert.assert_awaited_once()
    finally:
        _stop(started)


@pytest.mark.asyncio
async def test_extraction_failure_triggers_best_effort_purge() -> None:
    job, session = _job(), _session()

    async def _extract_boom(video_path, wav_path):
        raise RuntimeError("ffmpeg_exit_1")

    started = _patches(job, session, extract=_extract_boom)
    try:
        await vi._run_video_import_in_background(session.id, job.id)
        # Extraction failed BEFORE the main-path purge → the failure handler
        # best-effort purges so no unmasked video is left behind.
        assert vi.purge_raw_video.await_count == 1
        vi.run_stage1.assert_not_awaited()
        vi.jobs.mark_failed.assert_awaited_once()
    finally:
        _stop(started)
