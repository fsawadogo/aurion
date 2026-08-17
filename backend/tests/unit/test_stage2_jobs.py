"""M-07 / B-06: Stage 2 background job state machine.

Validates the pending → running → completed/failed transitions, and that
terminal states are non-clobberable (a stale completion can't overwrite a
recorded failure). Mocks the SQLAlchemy session — the jobs module is pure
state-machine logic on top of a single row.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.models import Stage2JobModel
from app.modules.vision.jobs import (
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    STAGE2_DEADLINE_REASON,
    STAGE2_FAILURE_REASON,
    STALE_RUNNING_BUDGET_S,
    Stage2DeadlineExceededError,
    create_job,
    get_latest_job,
    mark_completed,
    mark_failed,
    mark_running,
    public_stage2_failure_reason,
    run_with_stage2_deadline,
    stage2_hard_deadline_seconds,
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
    existing = Stage2JobModel(id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING)
    db = _mock_db_with(scalar_result=existing)

    await mark_running(existing.id, db)

    assert existing.status == JOB_RUNNING
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_transition_persists_new_version():
    existing = Stage2JobModel(id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING)
    db = _mock_db_with(scalar_result=existing.id)

    transitioned = await mark_completed(
        existing.id,
        new_note_version=3,
        frames_processed=12,
        db=db,
    )

    assert transitioned is True
    statement = db.execute.await_args.args[0]
    params = statement.compile().params
    assert params["status"] == JOB_COMPLETED
    assert params["status_1"] == JOB_RUNNING
    assert params["new_note_version"] == 3
    assert params["frames_processed"] == 12
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_transition_replaces_raw_error_with_public_reason_code():
    existing = Stage2JobModel(id=uuid.uuid4(), session_id=uuid.uuid4(), status=JOB_RUNNING)
    db = _mock_db_with(scalar_result=existing.id)
    raw_error = "model returned patient text"

    transitioned = await mark_failed(existing.id, raw_error, db)

    assert transitioned is True
    statement = db.execute.await_args.args[0]
    params = statement.compile().params
    assert params["status"] == JOB_FAILED
    assert params["status_1"] == [JOB_PENDING, JOB_RUNNING]
    assert params["error_message"] == STAGE2_FAILURE_REASON
    assert raw_error not in str(params)
    db.commit.assert_awaited_once()


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
    db = _mock_db_with(scalar_result=None)

    transitioned = await mark_completed(
        existing.id,
        new_note_version=2,
        frames_processed=4,
        db=db,
    )

    assert transitioned is False
    assert existing.status == JOB_FAILED
    assert existing.new_note_version is None
    assert existing.error_message == "provider unavailable"
    db.commit.assert_not_awaited()


def test_public_stage2_failure_reason_hides_legacy_raw_messages() -> None:
    assert public_stage2_failure_reason(None) is None
    assert public_stage2_failure_reason(STAGE2_DEADLINE_REASON) == STAGE2_DEADLINE_REASON
    assert public_stage2_failure_reason("patient/model text") == STAGE2_FAILURE_REASON


@pytest.mark.asyncio
async def test_stage2_status_never_returns_legacy_raw_error_text() -> None:
    from app.api.v1 import notes as notes_routes

    session_id = uuid.uuid4()
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=JOB_FAILED,
        started_at=None,
        completed_at=None,
        new_note_version=None,
        frames_processed=0,
        error_message="patient/model text from a legacy row",
    )
    with (
        patch.object(notes_routes, "get_owned_session_or_404", AsyncMock()),
        patch.object(notes_routes, "get_latest_job", AsyncMock(return_value=job)),
        patch.object(notes_routes, "fail_if_stale", AsyncMock(return_value=False)),
    ):
        response = await notes_routes.get_stage2_status(
            session_id,
            user=SimpleNamespace(),
            db=AsyncMock(),
        )

    assert response.error_message == STAGE2_FAILURE_REASON


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


@pytest.mark.asyncio
async def test_owner_deadline_cancels_the_awaited_stage2_chain() -> None:
    """The hard deadline stops active work; it does not merely fail a DB row."""
    cancelled = asyncio.Event()

    async def never_finishes() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    config = SimpleNamespace(
        alerting=SimpleNamespace(sla_stage2_ms=10),
    )
    with patch(
        "app.modules.vision.jobs.get_config",
        return_value=config,
    ):
        with pytest.raises(Stage2DeadlineExceededError, match="hard deadline"):
            await run_with_stage2_deadline(never_finishes())

    assert cancelled.is_set()


def test_owner_deadline_is_always_below_the_orphan_reaper() -> None:
    config = SimpleNamespace(
        alerting=SimpleNamespace(sla_stage2_ms=86_400_000),
    )
    with patch(
        "app.modules.vision.jobs.get_config",
        return_value=config,
    ):
        assert stage2_hard_deadline_seconds() < STALE_RUNNING_BUDGET_S


@pytest.mark.asyncio
async def test_notes_background_deadline_rolls_back_and_records_failure() -> None:
    """The normal approve-Stage-1 owner uses the shared cancelling deadline."""
    from app.api.v1 import notes as notes_routes

    session_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db = AsyncMock()
    cancelled = asyncio.Event()
    order: list[str] = []

    class _SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    async def never_finishes(*_args) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def rollback() -> None:
        order.append("rollback")

    async def failed(*_args, **_kwargs) -> bool:
        order.append("failed")
        return True

    db.rollback.side_effect = rollback
    config = SimpleNamespace(
        alerting=SimpleNamespace(sla_stage2_ms=10),
    )
    with (
        patch.object(notes_routes, "async_session_factory", return_value=_SessionContext()),
        patch.object(notes_routes, "mark_running", AsyncMock()),
        patch.object(notes_routes, "mark_failed", AsyncMock(side_effect=failed)) as mark_failed_mock,
        patch.object(notes_routes, "mark_completed", AsyncMock()) as mark_completed_mock,
        patch.object(notes_routes, "write_audit", AsyncMock()) as write_audit_mock,
        patch.object(notes_routes, "try_publish_alert", AsyncMock()),
        patch("app.api.v1.vision.run_stage2_vision", side_effect=never_finishes),
        patch("app.modules.vision.jobs.get_config", return_value=config),
    ):
        await notes_routes._run_stage2_in_background(session_id, job_id)

    assert cancelled.is_set()
    assert order == ["rollback", "failed"]
    mark_failed_mock.assert_awaited_once()
    assert mark_failed_mock.await_args.args[1] == STAGE2_DEADLINE_REASON
    mark_completed_mock.assert_not_awaited()
    assert write_audit_mock.await_args.args[1].value == "stage2_failed"
    assert write_audit_mock.await_args.kwargs["reason"] == STAGE2_DEADLINE_REASON


@pytest.mark.asyncio
async def test_notes_owner_audits_only_after_durable_completion() -> None:
    from app.api.v1 import notes as notes_routes

    session_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db = AsyncMock()
    order: list[str] = []

    class _SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    async def completed(*_args, **_kwargs) -> bool:
        order.append("commit")
        return True

    async def audited(*_args, **_kwargs) -> None:
        order.append("audit")

    result = SimpleNamespace(frames_processed=7)
    latest = SimpleNamespace(version=2)
    with (
        patch.object(
            notes_routes,
            "async_session_factory",
            return_value=_SessionContext(),
        ),
        patch.object(notes_routes, "mark_running", AsyncMock()),
        patch.object(
            notes_routes,
            "mark_completed",
            AsyncMock(side_effect=completed),
        ),
        patch.object(notes_routes, "mark_failed", AsyncMock()) as failed_mock,
        patch.object(notes_routes, "get_latest_note", AsyncMock(return_value=latest)),
        patch("app.api.v1.vision.run_stage2_vision", AsyncMock(return_value=result)),
        patch(
            "app.api.v1.vision.write_stage2_completion_audit",
            AsyncMock(side_effect=audited),
        ),
    ):
        await notes_routes._run_stage2_in_background(session_id, job_id)

    assert order == ["commit", "audit"]
    failed_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_notes_owner_rolls_back_note_and_skips_audit_when_completion_loses() -> None:
    from app.api.v1 import notes as notes_routes

    session_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db = AsyncMock()

    class _SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    result = SimpleNamespace(frames_processed=3)
    with (
        patch.object(notes_routes, "async_session_factory", return_value=_SessionContext()),
        patch.object(notes_routes, "mark_running", AsyncMock()),
        patch.object(notes_routes, "mark_completed", AsyncMock(return_value=False)),
        patch.object(notes_routes, "mark_failed", AsyncMock()) as mark_failed_mock,
        patch.object(notes_routes, "get_latest_note", AsyncMock(return_value=SimpleNamespace(version=2))),
        patch("app.api.v1.vision.run_stage2_vision", AsyncMock(return_value=result)),
        patch("app.api.v1.vision.write_stage2_completion_audit", AsyncMock()) as audit_mock,
    ):
        await notes_routes._run_stage2_in_background(session_id, job_id)

    db.rollback.assert_awaited_once()
    audit_mock.assert_not_awaited()
    mark_failed_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_notes_failure_loser_emits_no_terminal_audit_or_alert(caplog) -> None:
    from app.api.v1 import notes as notes_routes

    session_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db = AsyncMock()

    class _SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    sensitive = "patient said sensitive model text"
    with (
        patch.object(notes_routes, "async_session_factory", return_value=_SessionContext()),
        patch.object(notes_routes, "mark_running", AsyncMock()),
        patch.object(notes_routes, "mark_failed", AsyncMock(return_value=False)) as failed_mock,
        patch.object(notes_routes, "write_audit", AsyncMock()) as audit_mock,
        patch.object(notes_routes, "try_publish_alert", AsyncMock()) as alert_mock,
        patch("app.api.v1.vision.run_stage2_vision", AsyncMock(side_effect=RuntimeError(sensitive))),
    ):
        await notes_routes._run_stage2_in_background(session_id, job_id)

    failed_mock.assert_awaited_once()
    assert failed_mock.await_args.args[1] == STAGE2_FAILURE_REASON
    audit_mock.assert_not_awaited()
    alert_mock.assert_not_awaited()
    assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_direct_vision_route_is_retired_in_favour_of_job_owner() -> None:
    from fastapi import HTTPException

    from app.api.v1 import vision as vision_routes

    session_id = uuid.uuid4()
    session = SimpleNamespace(state=SimpleNamespace(value="processing_stage2"))
    run_mock = AsyncMock()
    with (
        patch.object(
            vision_routes,
            "get_owned_session_or_404",
            AsyncMock(return_value=session),
        ),
        patch.object(vision_routes, "require_state"),
        patch.object(vision_routes, "run_stage2_vision", run_mock),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await vision_routes.process_vision_frames(
                session_id,
                user=SimpleNamespace(),
                db=AsyncMock(),
            )

    assert exc_info.value.status_code == 409
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_audit_is_derived_from_committed_result() -> None:
    from app.api.v1 import vision as vision_routes

    session_id = uuid.uuid4()
    result = vision_routes.VisionProcessingResponse(
        session_id=str(session_id),
        frames_processed=0,
        frames_discarded=0,
        enriches_count=0,
        repeats_count=0,
        conflicts_count=0,
        captions=[],
    )
    audit = AsyncMock()
    with patch.object(vision_routes, "write_audit", audit):
        await vision_routes.write_stage2_completion_audit(session_id, result)

    audit.assert_awaited_once()
    assert audit.await_args.args[1].value == "stage2_complete"
    assert audit.await_args.kwargs["reason"] == "no_visual_evidence"
