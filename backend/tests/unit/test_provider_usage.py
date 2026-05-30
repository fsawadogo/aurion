"""Unit tests for ProviderUsageService (issue #73 foundation).

AsyncMock pattern — matches test_alert_service.py / test_auth_active.py
so the suite stays pure-Python (no extra DB driver dependency).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import ProviderUsageModel
from app.modules.providers.usage_service import (
    ProviderUsageService,
    UsageTotals,
    get_provider_usage_service,
)


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _exec_result(scalar_one: object = None, rows: list | None = None) -> MagicMock:
    """A mock execute() result usable for either scalar fetches or rowsets."""
    result = MagicMock()
    result.one = MagicMock(return_value=scalar_one)
    result.all = MagicMock(return_value=rows or [])
    return result


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_persists_row(self) -> None:
        svc = ProviderUsageService()
        db = _mock_db()

        rid = await svc.record(
            db,
            provider_type="note_generation",
            provider_name="openai",
            operation="generate_note",
            latency_ms=1234,
            success=True,
            fallback_used=False,
            session_id=uuid.uuid4(),
        )

        assert isinstance(rid, uuid.UUID)
        assert db.add.call_count == 1
        added = db.add.call_args.args[0]
        assert isinstance(added, ProviderUsageModel)
        assert added.id == rid
        assert added.provider_type == "note_generation"
        assert added.provider_name == "openai"
        assert added.operation == "generate_note"
        assert added.latency_ms == 1234
        assert added.success is True
        assert added.fallback_used is False
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_failure_path(self) -> None:
        svc = ProviderUsageService()
        db = _mock_db()
        await svc.record(
            db,
            provider_type="vision",
            provider_name="anthropic",
            operation="caption_frame",
            latency_ms=500,
            success=False,
            fallback_used=True,
        )
        added = db.add.call_args.args[0]
        assert added.success is False
        assert added.fallback_used is True


class TestAggregate:
    @pytest.mark.asyncio
    async def test_aggregate_empty_window(self) -> None:
        svc = ProviderUsageService()
        db = _mock_db()
        # totals row when empty — counts/sums all zero or null
        db.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar_one=(0, 0, 0, 0, 0.0, 0, 0, 0.0)),
                _exec_result(rows=[]),
            ]
        )

        totals, by_provider = await svc.aggregate(db)

        assert isinstance(totals, UsageTotals)
        assert totals.call_count == 0
        assert totals.avg_latency_ms == 0.0
        assert by_provider == []

    @pytest.mark.asyncio
    async def test_aggregate_computes_rates(self) -> None:
        svc = ProviderUsageService()
        db = _mock_db()
        # Totals: 10 calls, 9 successes, 1 failure, 2 fallbacks, 800ms avg.
        # By-provider: openai 8/8/0/0, anthropic 2/1/1/2.
        db.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar_one=(10, 9, 1, 2, 800.0, 1000, 500, 0.42)),
                _exec_result(
                    rows=[
                        ("note_generation", "openai", 8, 8, 0, 0, 700.0, 800, 400, 0.30),
                        ("note_generation", "anthropic", 2, 1, 1, 2, 1200.0, 200, 100, 0.12),
                    ]
                ),
            ]
        )

        totals, by_provider = await svc.aggregate(db)

        assert totals.call_count == 10
        assert totals.success_count == 9
        assert totals.fallback_count == 2
        assert totals.avg_latency_ms == 800.0

        assert len(by_provider) == 2
        oa = next(r for r in by_provider if r.provider_name == "openai")
        an = next(r for r in by_provider if r.provider_name == "anthropic")
        assert oa.call_count == 8
        assert oa.success_rate == 1.0
        assert oa.fallback_rate == 0.0
        assert an.call_count == 2
        assert an.success_rate == 0.5
        assert an.fallback_rate == 1.0

    @pytest.mark.asyncio
    async def test_aggregate_with_filters_does_not_raise(self) -> None:
        from datetime import datetime, timezone

        svc = ProviderUsageService()
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar_one=(0, 0, 0, 0, 0.0, 0, 0, 0.0)),
                _exec_result(rows=[]),
            ]
        )
        await svc.aggregate(
            db,
            since=datetime.now(timezone.utc),
            until=datetime.now(timezone.utc),
            provider_type="note_generation",
        )
        assert db.execute.await_count == 2


class TestCompare:
    @pytest.mark.asyncio
    async def test_compare_both_present(self) -> None:
        svc = ProviderUsageService()
        db = _mock_db()
        # Two aggregate() calls are made — each returns the same rollups
        # list because `aggregate` doesn't filter by provider_name. We
        # prime two identical results.
        rows = [
            ("note_generation", "openai", 8, 8, 0, 0, 700.0, 800, 400, 0.30),
            ("note_generation", "anthropic", 2, 1, 1, 2, 1200.0, 200, 100, 0.12),
        ]
        db.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar_one=(10, 9, 1, 2, 800.0, 1000, 500, 0.42)),
                _exec_result(rows=rows),
                _exec_result(scalar_one=(10, 9, 1, 2, 800.0, 1000, 500, 0.42)),
                _exec_result(rows=rows),
            ]
        )

        out = await svc.compare(
            db, provider_type="note_generation", a="openai", b="anthropic"
        )

        assert out.a == "openai"
        assert out.b == "anthropic"
        assert out.a_rollup is not None
        assert out.b_rollup is not None
        assert out.a_rollup.provider_name == "openai"
        assert out.b_rollup.provider_name == "anthropic"
        # Delta = b - a → anthropic (1200ms) - openai (700ms) = 500ms
        assert out.delta.avg_latency_ms == 500.0
        # openai success_rate = 1.0, anthropic = 0.5 → delta -0.5
        assert out.delta.success_rate == -0.5
        # openai fallback_rate = 0.0, anthropic = 1.0 → delta 1.0
        assert out.delta.fallback_rate == 1.0

    @pytest.mark.asyncio
    async def test_compare_missing_provider(self) -> None:
        svc = ProviderUsageService()
        db = _mock_db()
        # Empty rows on both aggregate calls — neither provider has data.
        empty = (0, 0, 0, 0, 0.0, 0, 0, 0.0)
        db.execute = AsyncMock(
            side_effect=[
                _exec_result(scalar_one=empty),
                _exec_result(rows=[]),
                _exec_result(scalar_one=empty),
                _exec_result(rows=[]),
            ]
        )
        out = await svc.compare(
            db, provider_type="note_generation", a="openai", b="anthropic"
        )
        assert out.a_rollup is None
        assert out.b_rollup is None
        assert out.delta.avg_latency_ms == 0.0
        assert out.delta.success_rate == 0.0
        assert out.delta.fallback_rate == 0.0


class TestServiceFactory:
    def test_get_provider_usage_service_is_singleton(self) -> None:
        a = get_provider_usage_service()
        b = get_provider_usage_service()
        assert a is b
