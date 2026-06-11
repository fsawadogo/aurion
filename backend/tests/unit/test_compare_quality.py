"""OV-3 (#74): per-provider quality aggregation + the compare-quality route.

The repository function is exercised against a mocked session (asserting
the emitted SQL shape: NULL-attribution exclusion, grouping, window
filters) and the row→dict mapping; the route is pinned by registration +
response-shape tests, mirroring the house pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.eval.repository import aggregate_scores_by_provider


def _row(provider: str, n: int, overall: float) -> MagicMock:
    r = MagicMock()
    r.provider_used = provider
    r.scored_sessions = n
    r.avg_overall = overall
    r.avg_transcript_accuracy = overall
    r.avg_citation_correctness = overall
    r.avg_descriptive_mode_compliance = overall
    r.avg_hallucination_count = 0.5
    return r


def test_route_registered_with_eval_gate() -> None:
    from app.api.v1.admin.providers import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/admin/providers/compare-quality", ("GET",)) in paths


def test_response_model_shape() -> None:
    from app.api.v1.admin.providers import (
        ProviderQualityCompareResponse,
        ProviderQualityRow,
    )

    row = ProviderQualityRow(
        provider_name="gemini",
        scored_sessions=4,
        avg_overall=0.91,
        avg_transcript_accuracy=0.93,
        avg_citation_correctness=0.95,
        avg_descriptive_mode_compliance=1.0,
        avg_hallucination_count=0.25,
    )
    resp = ProviderQualityCompareResponse(since=None, until=None, providers=[row])
    assert resp.providers[0].scored_sessions == 4
    # Averages are nullable — a provider with no parseable values renders
    # null, never a fake zero.
    ProviderQualityRow(
        provider_name="openai", scored_sessions=0,
        avg_overall=None, avg_transcript_accuracy=None,
        avg_citation_correctness=None, avg_descriptive_mode_compliance=None,
        avg_hallucination_count=None,
    )


@pytest.mark.asyncio
async def test_aggregation_maps_rows_and_floats() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = [_row("gemini", 5, 0.9), _row("anthropic", 2, 0.8)]
    db.execute = AsyncMock(return_value=result)

    rows = await aggregate_scores_by_provider(db)

    assert [r["provider_name"] for r in rows] == ["gemini", "anthropic"]
    assert rows[0]["scored_sessions"] == 5
    assert isinstance(rows[0]["avg_overall"], float)
    assert rows[1]["avg_hallucination_count"] == 0.5


@pytest.mark.asyncio
async def test_aggregation_sql_excludes_null_attribution_and_windows() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    until = datetime(2026, 6, 11, tzinfo=timezone.utc)
    await aggregate_scores_by_provider(db, since=since, until=until)

    sql = str(db.execute.call_args.args[0].compile())
    assert "provider_used IS NOT NULL" in sql
    assert "GROUP BY" in sql and "provider_used" in sql
    assert "scored_at >= :scored_at_1" in sql   # since bound
    assert "scored_at <= :scored_at_2" in sql   # until bound
