"""Unit tests for video-import startup orphan recovery (vid-offload-blocking).

A container recycle kills the fire-and-forget orchestrator task before its
``except -> mark_failed`` runs, stranding the job ``running``. The startup sweep
reaps such jobs (budget-gated) so they fail + become re-runnable without waiting
for a status poll — complementing the per-poll watchdog.
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
    )
    base.update(over)
    return SimpleNamespace(**base)


def _execute_returning(rows):
    """A db.execute result whose .scalars().all() yields ``rows``."""
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


class _FakeSession:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


# ── jobs.recover_orphaned_jobs (AC-3) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_reaps_stale_running() -> None:
    db = AsyncMock()
    stale = _job()
    db.execute = AsyncMock(return_value=_execute_returning([stale]))

    reaped = await jobs.recover_orphaned_jobs(db)

    assert reaped == [stale.session_id]
    assert stale.status == "failed"


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_leaves_fresh_running() -> None:
    db = AsyncMock()
    fresh = _job(started_at=utcnow() - timedelta(seconds=5))
    db.execute = AsyncMock(return_value=_execute_returning([fresh]))

    reaped = await jobs.recover_orphaned_jobs(db)

    assert reaped == []
    assert fresh.status == "running"


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_empty_when_none_running() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_execute_returning([]))

    assert await jobs.recover_orphaned_jobs(db) == []


# ── recover_stuck_imports_on_startup (AC-4) ──────────────────────────────────


@pytest.mark.asyncio
async def test_startup_recovery_audits_each_reaped_session() -> None:
    sid = uuid.uuid4()
    with patch.object(
        vi.jobs, "recover_orphaned_jobs", AsyncMock(return_value=[sid])
    ), patch.object(vi, "write_audit", AsyncMock()) as audit, patch.object(
        vi, "async_session_factory", lambda: _FakeSession()
    ):
        count = await vi.recover_stuck_imports_on_startup()

    assert count == 1
    audit.assert_awaited_once()
    assert audit.await_args.args[0] == sid
    assert audit.await_args.args[1] == AuditEventType.VIDEO_IMPORT_FAILED


@pytest.mark.asyncio
async def test_startup_recovery_no_audit_when_nothing_reaped() -> None:
    with patch.object(
        vi.jobs, "recover_orphaned_jobs", AsyncMock(return_value=[])
    ), patch.object(vi, "write_audit", AsyncMock()) as audit, patch.object(
        vi, "async_session_factory", lambda: _FakeSession()
    ):
        count = await vi.recover_stuck_imports_on_startup()

    assert count == 0
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_recovery_swallows_errors() -> None:
    """Best-effort: a failure must never block app startup."""
    def _boom():
        raise RuntimeError("db unavailable")

    with patch.object(vi, "async_session_factory", _boom):
        assert await vi.recover_stuck_imports_on_startup() == 0
