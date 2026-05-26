"""Unit tests for WEB-METRICS-CHARTS daily-aggregation endpoint.

Covers the 5 backend AC tests from
docs/plans/WEB-METRICS-CHARTS-pilot-metrics-time-series.md. Uses the
FastAPI TestClient with a mocked-out auth + AsyncSession so we don't
need docker or a real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_timeseries_endpoint_registered() -> None:
    """The new endpoint must be wired into the admin router."""
    from app.api.v1.admin.metrics import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/admin/metrics/timeseries", ("GET",)) in paths


def test_timeseries_response_schema_shape() -> None:
    """Response model must carry from/to/bucket/buckets."""
    from app.api.v1.admin._shared import (
        MetricTimeseriesBucket,
        MetricTimeseriesResponse,
    )

    bucket = MetricTimeseriesBucket(
        date="2026-05-26",
        session_count=2,
        template_section_completeness=0.95,
        session_completeness=100.0,
    )
    assert bucket.session_count == 2
    assert bucket.physician_edit_rate is None  # explicitly null by spec

    # `from` is a Python keyword; the schema uses an alias.
    resp = MetricTimeseriesResponse(
        **{"from": "2026-05-12", "to": "2026-05-26"},
        bucket="day",
        buckets=[bucket],
    )
    assert resp.from_date == "2026-05-12"
    assert resp.to_date == "2026-05-26"
    assert len(resp.buckets) == 1
    assert resp.bucket == "day"

    dumped = resp.model_dump(by_alias=True)
    assert "from" in dumped and dumped["from"] == "2026-05-12"


def _fake_row(
    day: datetime,
    session_count: int = 1,
    template: float | None = None,
    citation: float | None = None,
    conflict: float | None = None,
    low_conf: float | None = None,
    stage1: float | None = None,
    stage2: float | None = None,
    completeness_pct: float | None = None,
):
    r = MagicMock()
    r.day = day
    r.session_count = session_count
    r.template_section_completeness = template
    r.citation_traceability_rate = citation
    r.conflict_rate = conflict
    r.low_confidence_frame_rate = low_conf
    r.stage1_latency_ms = stage1
    r.stage2_latency_ms = stage2
    r.session_completeness = completeness_pct
    return r


@pytest.mark.asyncio
async def test_timeseries_returns_one_bucket_per_day() -> None:
    """AC-1: 15-day window returns 15 buckets, with empty days filled
    in as session_count=0 + all metrics None."""
    from app.api.v1.admin.metrics import get_metrics_timeseries
    from app.core.types import UserRole

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(
            all=lambda: [
                _fake_row(
                    datetime(2026, 5, 20, tzinfo=timezone.utc),
                    session_count=2,
                    template=0.85,
                )
            ]
        )
    )
    user = MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4())

    resp = await get_metrics_timeseries(
        from_="2026-05-12",
        to="2026-05-26",
        specialty=None,
        clinician_id=None,
        user=user,
        db=db,
    )

    # 15 inclusive (May 12 → May 26)
    assert len(resp.buckets) == 15
    assert resp.from_date == "2026-05-12"
    assert resp.to_date == "2026-05-26"

    by_date = {b.date: b for b in resp.buckets}
    assert by_date["2026-05-20"].session_count == 2
    assert by_date["2026-05-20"].template_section_completeness == pytest.approx(0.85)
    # Days with no data are filled in.
    assert by_date["2026-05-13"].session_count == 0
    assert by_date["2026-05-13"].template_section_completeness is None


@pytest.mark.asyncio
async def test_timeseries_filters_by_clinician() -> None:
    """AC-2: clinician_id filter narrows the WHERE clause."""
    from app.api.v1.admin.metrics import get_metrics_timeseries
    from app.core.types import UserRole

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    user = MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4())

    cid = str(uuid.uuid4())
    await get_metrics_timeseries(
        from_="2026-05-20",
        to="2026-05-26",
        specialty=None,
        clinician_id=cid,
        user=user,
        db=db,
    )

    # The compiled statement must reference clinician_id.
    stmt = db.execute.await_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "clinician_id" in compiled


@pytest.mark.asyncio
async def test_timeseries_session_completeness_is_percentage() -> None:
    """AC-3: When session_completeness is a float (0-100 from SQL
    AVG(bool::int)*100), it surfaces directly in the bucket."""
    from app.api.v1.admin.metrics import get_metrics_timeseries
    from app.core.types import UserRole

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(
            all=lambda: [
                _fake_row(
                    datetime(2026, 5, 25, tzinfo=timezone.utc),
                    session_count=1,
                    completeness_pct=100.0,
                )
            ]
        )
    )
    user = MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4())

    resp = await get_metrics_timeseries(
        from_="2026-05-25",
        to="2026-05-25",
        specialty=None,
        clinician_id=None,
        user=user,
        db=db,
    )
    assert len(resp.buckets) == 1
    assert resp.buckets[0].session_completeness == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_timeseries_averages_numeric_metrics() -> None:
    """AC-4: Numeric metrics come back as floats — averaging happens
    inside SQL (AVG()), the route just passes through. This test
    confirms float-pass-through is wired correctly (no off-by-100
    or accidental int truncation)."""
    from app.api.v1.admin.metrics import get_metrics_timeseries
    from app.core.types import UserRole

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(
            all=lambda: [
                _fake_row(
                    datetime(2026, 5, 25, tzinfo=timezone.utc),
                    session_count=2,
                    stage1=12345.5,  # 2 sessions, one 12000ms one 12691ms → avg
                    citation=0.94,
                )
            ]
        )
    )
    user = MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4())

    resp = await get_metrics_timeseries(
        from_="2026-05-25",
        to="2026-05-25",
        specialty=None,
        clinician_id=None,
        user=user,
        db=db,
    )
    assert resp.buckets[0].stage1_latency_ms == pytest.approx(12345.5)
    assert resp.buckets[0].citation_traceability_rate == pytest.approx(0.94)


def test_clinician_cannot_access_timeseries() -> None:
    """AC-5: The route is guarded by require_role(EVAL_TEAM, ADMIN).
    Confirm the FastAPI dependency tree includes the role gate."""
    # The Depends() default carries the role-checker. We inspect the
    # function's signature for the user param and confirm it has a
    # Depends-wrapped require_role call.
    import inspect

    from app.api.v1.admin.metrics import get_metrics_timeseries

    sig = inspect.signature(get_metrics_timeseries)
    user_param = sig.parameters["user"]
    assert user_param.default is not None
    # The default is `Depends(require_role(...))`. require_role returns
    # a callable; we just need to know one is present.
    assert user_param.default.dependency.__qualname__.startswith("require_role")


@pytest.mark.asyncio
async def test_timeseries_default_window_last_14_days() -> None:
    """When no from/to is given, the window is the last 14 calendar days."""
    from app.api.v1.admin.metrics import get_metrics_timeseries
    from app.core.types import UserRole

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    user = MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4())

    resp = await get_metrics_timeseries(
        from_=None,
        to=None,
        specialty=None,
        clinician_id=None,
        user=user,
        db=db,
    )
    # 14 days inclusive
    assert len(resp.buckets) == 14
    # End is "today" (UTC)
    today = datetime.now(timezone.utc).date()
    assert resp.to_date == today.isoformat()
    assert resp.from_date == (today - timedelta(days=13)).isoformat()


@pytest.mark.asyncio
async def test_timeseries_swaps_inverted_window() -> None:
    """If from > to (operator error), the route swaps them rather
    than returning an empty window."""
    from app.api.v1.admin.metrics import get_metrics_timeseries
    from app.core.types import UserRole

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    user = MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4())

    resp = await get_metrics_timeseries(
        from_="2026-05-26",
        to="2026-05-20",  # inverted
        specialty=None,
        clinician_id=None,
        user=user,
        db=db,
    )
    assert resp.from_date == "2026-05-20"
    assert resp.to_date == "2026-05-26"
