"""Unit tests for video-import dispatch (bg-task-retain).

``start_processing`` must mark the job ``running`` synchronously BEFORE handing
off to the background task, and dispatch via ``spawn_background_task`` (retained
reference) rather than a bare ``asyncio.create_task``. The synchronous
mark-running closes the "stuck pending" gap: a dropped task is then recoverable
by the watchdog / startup sweep, and a duplicate ``/process`` is rejected.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import video_import as vi
from app.core.audit_events import AuditEventType
from app.core.types import SessionState


def _session():
    return SimpleNamespace(
        id=uuid.uuid4(),
        state=SessionState.CONSENT_PENDING,
        consent_confirmed=True,
    )


def _job(status: str = "pending"):
    return SimpleNamespace(
        id=uuid.uuid4(), status=status, raw_video_s3_key="vid/x.mp4"
    )


@pytest.mark.asyncio
async def test_marks_running_before_dispatch_via_spawn() -> None:
    session, job = _session(), _job()
    db = AsyncMock()

    # spawn must only be reached AFTER the job was marked running.
    def _spawn_side_effect(coro, name=None):
        vi.jobs.mark_running.assert_awaited()  # ordering: running first

    with patch.object(
        vi.jobs, "get_job_for_session", AsyncMock(return_value=job)
    ), patch.object(
        vi.jobs, "mark_running", AsyncMock(return_value=job)
    ) as mark_running, patch.object(
        vi, "get_s3_client", return_value=Mock()
    ), patch.object(vi, "write_audit", AsyncMock()) as audit, patch.object(
        vi, "_run_video_import_in_background", Mock(return_value=None)
    ), patch.object(
        vi, "spawn_background_task", Mock(side_effect=_spawn_side_effect)
    ) as spawn, patch.object(vi, "_status_response", Mock(return_value="STATUS")):
        result = await vi.start_processing(db, session, actor_id=uuid.uuid4())

    assert result == "STATUS"
    mark_running.assert_awaited_once_with(db, job)
    spawn.assert_called_once()
    assert spawn.call_args.kwargs.get("name") == "video-import"
    audit.assert_awaited_once()
    assert audit.await_args.args[1] == AuditEventType.VIDEO_IMPORT_STARTED


@pytest.mark.asyncio
async def test_duplicate_process_on_running_job_is_409() -> None:
    session, job = _session(), _job(status="running")
    with patch.object(vi.jobs, "get_job_for_session", AsyncMock(return_value=job)):
        with pytest.raises(HTTPException) as ei:
            await vi.start_processing(AsyncMock(), session, actor_id=uuid.uuid4())
    assert ei.value.status_code == 409
