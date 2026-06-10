"""Unit tests for the #76 synthesized alert detectors (SLA + purge gap).

The pass functions take an AsyncSession; we feed them a mock whose
``execute`` returns scripted rows, and assert against the AlertService
publish calls (patched). Env thresholds are exercised via monkeypatch.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.clock import utcnow
from app.modules.alerts import detectors
from app.modules.alerts.service import AlertSeverity


def _metric_row(s1=None, s2=None) -> MagicMock:
    row = MagicMock()
    row.session_id = uuid.uuid4()
    row.stage1_latency_ms = s1
    row.stage2_latency_ms = s2
    return row


def _session_row(hours_ago: float) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.updated_at = utcnow() - timedelta(hours=hours_ago)
    return row


def _db(scan_rows, dedup_rows_by_call=None):
    """Mock session: first execute returns the scan rows; subsequent
    executes (the dedup reads) return alert_metadata tuples."""
    db = AsyncMock()
    results = []

    scan = MagicMock()
    scan.all.return_value = scan_rows
    results.append(scan)

    for dedup in (dedup_rows_by_call or [[], []]):
        r = MagicMock()
        r.all.return_value = [(m,) for m in dedup]
        results.append(r)

    db.execute = AsyncMock(side_effect=results + [MagicMock(all=MagicMock(return_value=[]))] * 4)
    return db


@pytest.fixture
def mock_service():
    svc = MagicMock()
    svc.publish = AsyncMock()
    with patch.object(detectors, "get_alert_service", return_value=svc):
        yield svc


# ── SLA pass ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sla_pass_publishes_warning_over_threshold(mock_service) -> None:
    rows = [
        _metric_row(s1=45_000),                # breach (>30s default)
        _metric_row(s1=12_000),                # fine
        _metric_row(s2=400_000),               # stage2 breach (>5min default)
    ]
    n = await detectors.run_sla_pass(_db(rows))
    assert n == 2
    severities = [c.kwargs["severity"] for c in mock_service.publish.call_args_list]
    assert all(s == AlertSeverity.WARNING for s in severities)
    types = [c.kwargs["alert_type"] for c in mock_service.publish.call_args_list]
    assert types == [detectors.SLA_BREACH_STAGE1, detectors.SLA_BREACH_STAGE2]
    # Message carries seconds + the truncated session prefix, never a raw UUID-only blob.
    msg = mock_service.publish.call_args_list[0].kwargs["message"]
    assert "45.0s" in msg and "SLA 30s" in msg


@pytest.mark.asyncio
async def test_sla_pass_dedups_already_alerted_sessions(mock_service) -> None:
    row = _metric_row(s1=45_000)
    dedup = [{"session_id": str(row.session_id)}]
    n = await detectors.run_sla_pass(_db([row], dedup_rows_by_call=[dedup, []]))
    assert n == 0
    mock_service.publish.assert_not_called()


@pytest.mark.asyncio
async def test_sla_thresholds_respect_env(monkeypatch, mock_service) -> None:
    monkeypatch.setenv("AURION_SLA_STAGE1_MS", "60000")
    row = _metric_row(s1=45_000)  # under the raised threshold
    n = await detectors.run_sla_pass(_db([row]))
    assert n == 0
    mock_service.publish.assert_not_called()


# ── Purge-gap pass ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_gap_publishes_critical(mock_service) -> None:
    rows = [_session_row(hours_ago=30)]  # > 24h default window
    n = await detectors.run_purge_gap_pass(_db(rows))
    assert n == 1
    call = mock_service.publish.call_args.kwargs
    assert call["alert_type"] == detectors.PURGE_GAP
    assert call["severity"] == AlertSeverity.CRITICAL  # Slack-eligible
    assert call["metadata"]["window_hours"] == 24
    assert "still not purged" in call["message"]


@pytest.mark.asyncio
async def test_purge_gap_dedups(mock_service) -> None:
    row = _session_row(hours_ago=30)
    dedup = [{"session_id": str(row.id)}]
    n = await detectors.run_purge_gap_pass(_db([row], dedup_rows_by_call=[dedup]))
    assert n == 0
    mock_service.publish.assert_not_called()


# ── Worker lifecycle ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_noop_when_local(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    await detectors.start_alert_detectors()
    assert detectors._task is None
    await detectors.stop_alert_detectors()


@pytest.mark.asyncio
async def test_start_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AURION_ALERT_DETECTORS_ENABLED", "0")
    await detectors.start_alert_detectors()
    assert detectors._task is None


@pytest.mark.asyncio
async def test_pass_errors_are_swallowed() -> None:
    with patch.object(
        detectors, "async_session_factory", side_effect=RuntimeError("db down")
    ):
        n = await detectors.run_detector_pass()
    assert n == 0  # never raises
