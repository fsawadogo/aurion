"""Unit tests for the #77 compliance-report scheduler.

The pass is exercised with a patched session factory + reports service:
freshness gating (stale vs fresh), the since-window handed to generate
(gap since the newest report, or one full cadence for the first ever),
the shared single audit scan, env gating, and error swallowing.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.clock import utcnow
from app.modules.compliance import scheduler
from app.modules.compliance.reports_service import ReportType


def _factory_cm(session: AsyncMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _service(newest_by_type: dict) -> MagicMock:
    """Mock reports service: list() returns the scripted newest row per
    type; generate() records its kwargs."""
    svc = MagicMock()

    async def _list(db, *, report_type, limit=1, offset=0):
        row = newest_by_type.get(report_type)
        return [row] if row else []

    record = MagicMock()
    record.id = "rid"
    record.byte_size = 123
    svc.list = AsyncMock(side_effect=_list)
    svc.generate = AsyncMock(return_value=record)
    return svc


def _report_row(hours_ago: float) -> MagicMock:
    row = MagicMock()
    row.generated_at = utcnow() - timedelta(hours=hours_ago)
    return row


@pytest.mark.asyncio
async def test_first_ever_pass_generates_all_three_with_cadence_window() -> None:
    svc = _service({})  # no reports exist yet
    db = AsyncMock()
    with patch.object(scheduler, "get_compliance_reports_service", return_value=svc), \
         patch.object(scheduler, "async_session_factory", return_value=_factory_cm(db)):
        n = await scheduler.run_scheduler_pass(scan_events=AsyncMock(return_value=[]))

    assert n == 3
    types = [c.kwargs["report_type"] for c in svc.generate.call_args_list]
    assert set(types) == set(ReportType)
    # First-ever window = one full cadence back, not full history.
    since = svc.generate.call_args_list[0].kwargs["since"]
    age_hours = (utcnow() - since).total_seconds() / 3600
    assert abs(age_hours - scheduler.cadence_hours()) < 0.1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_fresh_reports_skip_generation() -> None:
    fresh = {t: _report_row(hours_ago=1) for t in ReportType}
    svc = _service(fresh)
    with patch.object(scheduler, "get_compliance_reports_service", return_value=svc), \
         patch.object(scheduler, "async_session_factory", return_value=_factory_cm(AsyncMock())):
        scan = AsyncMock(return_value=[])
        n = await scheduler.run_scheduler_pass(scan_events=scan)

    assert n == 0
    svc.generate.assert_not_called()
    scan.assert_not_called()  # nothing stale → the expensive scan never runs


@pytest.mark.asyncio
async def test_stale_report_regenerates_from_its_last_window() -> None:
    last = _report_row(hours_ago=200)  # > 168h default cadence
    newest = {ReportType.AUDIT: last,
              ReportType.MASKING: _report_row(hours_ago=1),
              ReportType.RETENTION: _report_row(hours_ago=1)}
    svc = _service(newest)
    scan = AsyncMock(return_value=[])
    with patch.object(scheduler, "get_compliance_reports_service", return_value=svc), \
         patch.object(scheduler, "async_session_factory", return_value=_factory_cm(AsyncMock())):
        n = await scheduler.run_scheduler_pass(scan_events=scan)

    assert n == 1
    call = svc.generate.call_args.kwargs
    assert call["report_type"] == ReportType.AUDIT
    # The new window starts where the last report ended — gap coverage,
    # no hole and no full-history rescan.
    assert call["since"] == last.generated_at
    scan.assert_awaited_once()  # one scan even if several types were stale


@pytest.mark.asyncio
async def test_pass_errors_swallowed() -> None:
    with patch.object(
        scheduler, "async_session_factory", side_effect=RuntimeError("db down")
    ):
        n = await scheduler.run_scheduler_pass(scan_events=AsyncMock(return_value=[]))
    assert n == 0  # never raises


@pytest.mark.asyncio
async def test_start_noop_when_local_or_disabled(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    await scheduler.start_report_scheduler()
    assert scheduler._task is None

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AURION_REPORT_SCHEDULER_ENABLED", "0")
    await scheduler.start_report_scheduler()
    assert scheduler._task is None
    await scheduler.stop_report_scheduler()


def test_cadence_env_clamped(monkeypatch) -> None:
    monkeypatch.setenv("AURION_REPORT_CADENCE_HOURS", "100000")
    assert scheduler.cadence_hours() == 720
    monkeypatch.setenv("AURION_REPORT_CADENCE_HOURS", "not a number")
    assert scheduler.cadence_hours() == 168
