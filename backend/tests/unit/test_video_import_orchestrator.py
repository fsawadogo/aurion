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


def _job(auto_advance_stage2: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        raw_video_s3_key=f"video-imports/{uuid.uuid4()}/v.mp4",
        raw_video_purged_at=None,
        status="running",
        auto_advance_stage2=auto_advance_stage2,
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
        patch.object(vi, "_extract_and_mask_frames", AsyncMock(return_value=(0, 0, 0))),
        patch.object(vi, "_auto_advance_stage2", AsyncMock(return_value=2)),
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
async def test_auto_advance_runs_stage2_when_flagged() -> None:
    job, session = _job(auto_advance_stage2=True), _session()
    started = _patches(job, session)
    try:
        await vi._run_video_import_in_background(session.id, job.id)
        vi._auto_advance_stage2.assert_awaited_once()
    finally:
        _stop(started)


@pytest.mark.asyncio
async def test_no_auto_advance_when_flag_off() -> None:
    job, session = _job(auto_advance_stage2=False), _session()
    started = _patches(job, session)
    try:
        await vi._run_video_import_in_background(session.id, job.id)
        vi._auto_advance_stage2.assert_not_awaited()
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


def _db_with_transcript(sid, *, trigger=True):
    from app.core.types import Transcript, TranscriptSegment

    seg = TranscriptSegment(
        id="seg_001", start_ms=1000, end_ms=2000, text="rom", is_visual_trigger=trigger
    )
    transcript = Transcript(session_id=str(sid), provider_used="whisper", segments=[seg])
    row = SimpleNamespace(transcript_json=transcript.model_dump_json())
    result_obj = MagicMock()
    result_obj.scalar_one_or_none = MagicMock(return_value=row)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_obj)
    return db


@pytest.mark.asyncio
async def test_extract_and_mask_frames_drops_audit_failures() -> None:
    """A masking failure stores NOTHING and audits SERVER_MASKING_FAILED."""
    sid = uuid.uuid4()
    db = _db_with_transcript(sid)
    s3 = MagicMock()
    fake_frames = [(1000, b"x"), (1500, b"y"), (2000, b"z")]
    with patch.object(
        vi, "extract_frames_at_windows", AsyncMock(return_value=fake_frames)
    ), patch.object(vi, "get_frame_window_ms", MagicMock(return_value=3000)), \
        patch.object(vi, "get_s3_client", MagicMock(return_value=s3)), \
        patch.object(vi, "write_audit", AsyncMock()) as audit, \
        patch.object(
            vi, "mask_frame",
            MagicMock(return_value=SimpleNamespace(
                status="failed", image_bytes=None, faces_detected=0,
                faces_blurred=0, reason="no_face_detected")),
        ):
        extracted, masked, dropped = await vi._extract_and_mask_frames(
            db, sid, "/tmp/v.mp4"
        )

    assert (extracted, masked, dropped) == (3, 0, 3)
    s3.put_object.assert_not_called()  # nothing stored
    events = [c.args[1] for c in audit.await_args_list]
    assert all(e == AuditEventType.SERVER_MASKING_FAILED for e in events)
    assert len(events) == 3


@pytest.mark.asyncio
async def test_extract_and_mask_frames_stores_successes() -> None:
    """A masked frame is put to frames/{sid}/{ts}.jpg + SERVER_MASKING_APPLIED."""
    sid = uuid.uuid4()
    db = _db_with_transcript(sid)
    s3 = MagicMock()
    with patch.object(
        vi, "extract_frames_at_windows", AsyncMock(return_value=[(1500, b"raw")])
    ), patch.object(vi, "get_frame_window_ms", MagicMock(return_value=3000)), \
        patch.object(vi, "get_s3_client", MagicMock(return_value=s3)), \
        patch.object(vi, "write_audit", AsyncMock()) as audit, \
        patch.object(
            vi, "mask_frame",
            MagicMock(return_value=SimpleNamespace(
                status="success", image_bytes=b"masked-jpeg", faces_detected=1,
                faces_blurred=1, reason=None)),
        ):
        extracted, masked, dropped = await vi._extract_and_mask_frames(
            db, sid, "/tmp/v.mp4"
        )

    assert (extracted, masked, dropped) == (1, 1, 0)
    _, kwargs = s3.put_object.call_args
    assert kwargs["Key"] == f"frames/{sid}/1500.jpg"
    assert kwargs["Body"] == b"masked-jpeg"
    assert audit.await_args.args[1] == AuditEventType.SERVER_MASKING_APPLIED


@pytest.mark.asyncio
async def test_extract_and_mask_frames_no_triggers_is_noop() -> None:
    """Pilot reality: empty trigger lists → zero frames extracted."""
    from app.core.types import Transcript, TranscriptSegment

    sid = uuid.uuid4()
    seg = TranscriptSegment(
        id="seg_001", start_ms=0, end_ms=500, text="hi", is_visual_trigger=False
    )
    transcript = Transcript(session_id=str(sid), provider_used="whisper", segments=[seg])
    row = SimpleNamespace(transcript_json=transcript.model_dump_json())
    result_obj = MagicMock()
    result_obj.scalar_one_or_none = MagicMock(return_value=row)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_obj)

    extract = AsyncMock()
    with patch.object(vi, "extract_frames_at_windows", extract):
        assert await vi._extract_and_mask_frames(db, sid, "/tmp/v.mp4") == (0, 0, 0)
    extract.assert_not_awaited()  # no triggers → ffmpeg never invoked


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


# ── _auto_advance_stage2 records a stage2_jobs row (the stuck-tile fix) ───────
#
# Regression for the Jun-2026 bug: video-import auto-advance ran Stage 2 to
# completion but never created a Stage2JobModel, so the iOS Stage-2 poll
# returned `no_job` forever and the dashboard tile stayed "Stage 2 queued"
# even though the full note was ready.


def _auto_advance_patches(*, stage2_raises: bool = False):
    job = SimpleNamespace(id=uuid.uuid4())
    approved = SimpleNamespace(
        version=1, provider_used="gemini", completeness_score=0.83
    )
    latest = SimpleNamespace(version=2)
    result = SimpleNamespace(frames_processed=7)
    run_stage2 = AsyncMock(
        side_effect=RuntimeError("boom") if stage2_raises else None,
        return_value=result,
    )
    mocks = {
        "create_job": AsyncMock(return_value=job),
        "mark_running": AsyncMock(),
        "mark_completed": AsyncMock(),
        "mark_failed": AsyncMock(),
        "run_stage2_vision": run_stage2,
        "approve_note": AsyncMock(return_value=approved),
        "get_latest_note": AsyncMock(return_value=latest),
        "job": job,
    }
    started = [
        patch("app.modules.vision.jobs.create_job", mocks["create_job"]),
        patch("app.modules.vision.jobs.mark_running", mocks["mark_running"]),
        patch("app.modules.vision.jobs.mark_completed", mocks["mark_completed"]),
        patch("app.modules.vision.jobs.mark_failed", mocks["mark_failed"]),
        patch("app.api.v1.vision.run_stage2_vision", mocks["run_stage2_vision"]),
        patch("app.modules.note_gen.service.approve_note", mocks["approve_note"]),
        patch(
            "app.modules.note_gen.service.get_latest_note",
            mocks["get_latest_note"],
        ),
        patch.object(vi, "transition_session", AsyncMock()),
        patch.object(vi, "write_audit", AsyncMock()),
    ]
    for p in started:
        p.start()
    return mocks, started


@pytest.mark.asyncio
async def test_auto_advance_creates_and_completes_stage2_job() -> None:
    mocks, started = _auto_advance_patches()
    try:
        db, session, sid = AsyncMock(), _session(), uuid.uuid4()
        version = await vi._auto_advance_stage2(db, session, sid)
    finally:
        for p in started:
            p.stop()

    assert version == 2
    # The marker the iOS poll relies on: created, run, completed with the
    # resulting note version + frames.
    mocks["create_job"].assert_awaited_once()
    mocks["mark_running"].assert_awaited_once()
    mocks["mark_completed"].assert_awaited_once()
    _, kwargs = mocks["mark_completed"].call_args
    assert kwargs["new_note_version"] == 2
    assert kwargs["frames_processed"] == 7
    mocks["mark_failed"].assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_advance_marks_job_failed_then_reraises() -> None:
    mocks, started = _auto_advance_patches(stage2_raises=True)
    try:
        db, session, sid = AsyncMock(), _session(), uuid.uuid4()
        with pytest.raises(RuntimeError):
            await vi._auto_advance_stage2(db, session, sid)
    finally:
        for p in started:
            p.stop()

    # Failure is recorded on the job (not left running) and bubbles so the
    # outer orchestrator still marks VIDEO_IMPORT_FAILED.
    mocks["mark_failed"].assert_awaited_once()
    mocks["mark_completed"].assert_not_awaited()
