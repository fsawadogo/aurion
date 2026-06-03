"""Unit tests for the clip-aware pilot_metrics path (P1-FU-METRICS).

Covers four surfaces:

1. ``cost_rates.estimate_cost_usd_micros`` — per-provider rate lookup +
   fallback for unknown providers/models.
2. ``clip_metrics.aggregate_clip_metrics`` — pure aggregator over a
   ``list[ClipTelemetry]``.
3. ``clip_metrics.record_clip_metrics`` — DB-bound upsert into
   ``pilot_metrics``, including create-new vs. update-existing branches.
4. ``PilotMetricsModel`` column declarations — the 5 new clip-aware
   columns are present with ``Integer`` types.

Mirrors the AsyncMock + MagicMock pattern from
``test_alert_service.py`` so the suite stays pure-Python.
"""

from __future__ import annotations

import logging
import re
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import PilotMetricsModel, SessionModel
from app.modules.vision.clip_metrics import (
    ClipTelemetry,
    aggregate_clip_metrics,
    record_clip_metrics,
)
from app.modules.vision.cost_rates import (
    USD_MICROS_PER_DOLLAR,
    VISION_RATES_USD_PER_MT,
    estimate_cost_usd_micros,
)


@pytest.fixture(autouse=True)
def _reset_aurion_loggers():
    """Re-enable Aurion module loggers and force INFO propagation.

    The integration suite calls Alembic via ``command.upgrade``, and
    Alembic's ``env.py`` invokes ``logging.config.fileConfig(...)``
    which has ``disable_existing_loggers=True`` by default. Any logger
    that was instantiated before fileConfig fires (e.g. by an earlier
    import of ``app.modules.vision.cost_rates``) gets ``disabled=True``,
    and ``caplog`` then captures nothing.

    Reaching into the logger registry is the simplest fix that keeps
    Alembic's own logger config untouched.
    """
    for name in (
        "aurion.vision.cost_rates",
        "aurion.vision.clip_metrics",
    ):
        lg = logging.getLogger(name)
        lg.disabled = False
        lg.setLevel(logging.INFO)
        lg.propagate = True
    yield


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    """AsyncSession mock with add() recording + flush() awaitable."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_execute_returning(value):
    """Build a ``result`` object such that ``result.scalar_one_or_none()``
    returns ``value`` — matches the shape SQLAlchemy returns from
    ``execute`` for a single-row select."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _telemetry(
    *,
    provider: str = "gemini",
    model: str = "gemini-2.5-pro",
    latency_ms: int = 1_000,
    input_tokens: int = 1_000,
    output_tokens: int = 500,
    degraded_to_frame: bool = False,
    bytes_uploaded: int = 1_500_000,
) -> ClipTelemetry:
    return ClipTelemetry(
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        degraded_to_frame=degraded_to_frame,
        bytes_uploaded=bytes_uploaded,
    )


# ── Model column declarations ──────────────────────────────────────────────


class TestPilotMetricsModelColumns:
    """The migration declares 5 new nullable Integer columns. Assert the
    SQLAlchemy model exposes them so the API serialization + ORM upsert
    stays type-safe."""

    def test_clip_count_column_present(self) -> None:
        col = PilotMetricsModel.clip_count.property.columns[0]
        assert str(col.type).upper() == "INTEGER"
        assert col.nullable is True

    def test_clip_bytes_uploaded_column_present(self) -> None:
        col = PilotMetricsModel.clip_bytes_uploaded.property.columns[0]
        assert str(col.type).upper() == "INTEGER"
        assert col.nullable is True

    def test_clip_avg_latency_ms_column_present(self) -> None:
        col = PilotMetricsModel.clip_avg_latency_ms.property.columns[0]
        assert str(col.type).upper() == "INTEGER"
        assert col.nullable is True

    def test_clip_vision_spend_column_present(self) -> None:
        col = PilotMetricsModel.clip_vision_spend_estimate_usd_micros.property.columns[0]
        assert str(col.type).upper() == "INTEGER"
        assert col.nullable is True

    def test_clip_degraded_to_frame_count_column_present(self) -> None:
        col = PilotMetricsModel.clip_degraded_to_frame_count.property.columns[0]
        assert str(col.type).upper() == "INTEGER"
        assert col.nullable is True


# ── Cost rate table ────────────────────────────────────────────────────────


class TestCostRateTable:
    """Phase 2 needs the rates baked in. Lock the three providers we
    expect at MVP launch so a careless edit can't drop one silently."""

    def test_gemini_pro_present(self) -> None:
        rates = VISION_RATES_USD_PER_MT["gemini"]["gemini-2.5-pro"]
        assert rates["input"] == 1.25
        assert rates["output"] == 5.00

    def test_openai_gpt4o_present(self) -> None:
        rates = VISION_RATES_USD_PER_MT["openai"]["gpt-4o"]
        assert rates["input"] == 2.50
        assert rates["output"] == 10.00

    def test_anthropic_sonnet_present(self) -> None:
        rates = VISION_RATES_USD_PER_MT["anthropic"]["claude-sonnet-4-6"]
        assert rates["input"] == 3.00
        assert rates["output"] == 15.00


class TestEstimateCostUsdMicros:
    def test_gemini_pro_known_value(self) -> None:
        # 10k input × $1.25/MT + 2k output × $5/MT
        # = 0.0125 + 0.01 = 0.0225 USD = 22_500 micros
        result = estimate_cost_usd_micros(
            provider="gemini",
            model="gemini-2.5-pro",
            input_tokens=10_000,
            output_tokens=2_000,
        )
        assert result == 22_500

    def test_openai_known_value(self) -> None:
        # 1k input × $2.50/MT + 500 output × $10/MT
        # = 0.0025 + 0.005 = 0.0075 USD = 7500 micros
        result = estimate_cost_usd_micros(
            provider="openai",
            model="gpt-4o",
            input_tokens=1_000,
            output_tokens=500,
        )
        assert result == 7_500

    def test_zero_tokens_zero_cost(self) -> None:
        assert (
            estimate_cost_usd_micros(
                provider="gemini",
                model="gemini-2.5-pro",
                input_tokens=0,
                output_tokens=0,
            )
            == 0
        )

    def test_unknown_provider_returns_zero_and_logs_info(self, caplog) -> None:
        """AC-5: unknown provider returns 0 + emits an INFO log so the
        eval team can spot the missing rate without breaking the metric."""
        with caplog.at_level(logging.INFO, logger="aurion.vision.cost_rates"):
            result = estimate_cost_usd_micros(
                provider="cohere",
                model="command-r-plus",
                input_tokens=1_000,
                output_tokens=500,
            )
        assert result == 0
        assert any(
            "unknown provider" in rec.message for rec in caplog.records
        ), f"Expected 'unknown provider' INFO log; got {[r.message for r in caplog.records]}"

    def test_unknown_model_returns_zero_and_logs_info(self, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="aurion.vision.cost_rates"):
            result = estimate_cost_usd_micros(
                provider="openai",
                model="gpt-5-turbo",
                input_tokens=1_000,
                output_tokens=500,
            )
        assert result == 0
        assert any(
            "unknown model" in rec.message for rec in caplog.records
        )

    def test_negative_tokens_clamped(self) -> None:
        """Defensive: providers occasionally return -1 on partial failures.
        Clamp to 0 rather than crashing or paying for negative tokens."""
        result = estimate_cost_usd_micros(
            provider="gemini",
            model="gemini-2.5-pro",
            input_tokens=-100,
            output_tokens=-50,
        )
        assert result == 0

    def test_case_insensitive_lookup(self) -> None:
        result = estimate_cost_usd_micros(
            provider="Gemini",
            model="Gemini-2.5-Pro",
            input_tokens=10_000,
            output_tokens=2_000,
        )
        assert result == 22_500

    def test_constant_value(self) -> None:
        """Scaling factor must equal 1e6 so callers can multiply USD by
        it to recover micros."""
        assert USD_MICROS_PER_DOLLAR == 1_000_000


# ── Aggregation ────────────────────────────────────────────────────────────


class TestAggregateClipMetrics:
    def test_empty_telemetries_returns_zero_count_null_mean(self) -> None:
        result = aggregate_clip_metrics([])
        assert result["clip_count"] == 0
        assert result["clip_bytes_uploaded"] == 0
        assert result["clip_avg_latency_ms"] is None
        assert result["clip_vision_spend_estimate_usd_micros"] is None
        assert result["clip_degraded_to_frame_count"] == 0

    def test_aggregate_mixed_evidence(self) -> None:
        """AC-3: three clips with mixed providers produce correct
        per-column aggregates."""
        telemetries = [
            _telemetry(provider="gemini", latency_ms=1_000, bytes_uploaded=1_000_000),
            _telemetry(
                provider="openai",
                model="gpt-4o",
                latency_ms=2_000,
                bytes_uploaded=2_000_000,
            ),
            _telemetry(
                provider="anthropic",
                model="claude-sonnet-4-6",
                latency_ms=3_000,
                bytes_uploaded=3_000_000,
                degraded_to_frame=True,
            ),
        ]
        result = aggregate_clip_metrics(telemetries)
        assert result["clip_count"] == 3
        assert result["clip_bytes_uploaded"] == 6_000_000
        assert result["clip_degraded_to_frame_count"] == 1

    def test_avg_latency(self) -> None:
        """AC-4: arithmetic mean of [1_000, 2_000, 3_000] = 2_000."""
        telemetries = [
            _telemetry(latency_ms=1_000),
            _telemetry(latency_ms=2_000),
            _telemetry(latency_ms=3_000),
        ]
        result = aggregate_clip_metrics(telemetries)
        assert result["clip_avg_latency_ms"] == 2_000

    def test_avg_latency_integer_floor(self) -> None:
        """Sub-ms precision is noise — column is Integer. Floor the mean."""
        telemetries = [
            _telemetry(latency_ms=1_000),
            _telemetry(latency_ms=1_001),
        ]
        result = aggregate_clip_metrics(telemetries)
        # (1000 + 1001) // 2 = 1000
        assert result["clip_avg_latency_ms"] == 1_000

    def test_spend_per_provider(self) -> None:
        """Per-clip spend sums across providers; each clip is priced
        against its own provider's rates."""
        telemetries = [
            _telemetry(
                provider="gemini",
                model="gemini-2.5-pro",
                input_tokens=10_000,
                output_tokens=2_000,
            ),
            _telemetry(
                provider="openai",
                model="gpt-4o",
                input_tokens=1_000,
                output_tokens=500,
            ),
        ]
        result = aggregate_clip_metrics(telemetries)
        # gemini: 22_500 + openai: 7_500 = 30_000 micros
        assert result["clip_vision_spend_estimate_usd_micros"] == 30_000

    def test_degraded_count_only_on_degraded_true(self) -> None:
        """Counter must NOT count non-degraded clips."""
        telemetries = [
            _telemetry(degraded_to_frame=False),
            _telemetry(degraded_to_frame=False),
            _telemetry(degraded_to_frame=True),
            _telemetry(degraded_to_frame=True),
        ]
        result = aggregate_clip_metrics(telemetries)
        assert result["clip_degraded_to_frame_count"] == 2

    def test_no_phi_in_telemetry_shape(self) -> None:
        """A ClipTelemetry carries no identifier fields beyond
        provider/model/byte/latency. Lock the dataclass surface so a
        future edit can't slip in patient identifiers."""
        from dataclasses import fields
        names = {f.name for f in fields(ClipTelemetry)}
        # Allow-list — these are the ONLY fields permitted.
        allowed = {
            "provider", "model", "latency_ms", "input_tokens",
            "output_tokens", "degraded_to_frame", "bytes_uploaded",
        }
        assert names == allowed, (
            f"ClipTelemetry surface drifted: extra={names - allowed} "
            f"missing={allowed - names}"
        )


# ── Persistence ────────────────────────────────────────────────────────────


class TestRecordClipMetrics:
    @pytest.mark.asyncio
    async def test_no_telemetries_is_noop(self) -> None:
        db = _mock_db()
        await record_clip_metrics(db, str(uuid.uuid4()), [])
        # No DB writes for a frame-only session.
        db.add.assert_not_called()
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_row_when_missing(self) -> None:
        """When no pilot_metrics row exists for the session, look up
        SessionModel for clinician_id + specialty and INSERT."""
        db = _mock_db()
        session_id = uuid.uuid4()
        clinician_id = uuid.uuid4()

        session_row = SessionModel(
            id=session_id,
            clinician_id=clinician_id,
            specialty="orthopedic_surgery",
        )

        # First execute() → no PilotMetricsModel row.
        # Second execute() → SessionModel row for clinician + specialty.
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_returning(None),
                _mock_execute_returning(session_row),
            ]
        )

        await record_clip_metrics(
            db,
            str(session_id),
            [_telemetry(latency_ms=1_500, bytes_uploaded=2_000_000)],
        )

        assert db.add.call_count == 1
        added = db.add.call_args.args[0]
        assert isinstance(added, PilotMetricsModel)
        assert added.clinician_id == clinician_id
        assert added.specialty == "orthopedic_surgery"
        assert added.clip_count == 1
        assert added.clip_bytes_uploaded == 2_000_000
        assert added.clip_avg_latency_ms == 1_500
        assert added.clip_degraded_to_frame_count == 0
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_row(self) -> None:
        """When a pilot_metrics row exists (e.g. Stage 1 latency already
        wrote it), update the clip columns in place."""
        db = _mock_db()
        session_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        existing = PilotMetricsModel(
            session_id=session_id,
            clinician_id=clinician_id,
            specialty="orthopedic_surgery",
            stage1_latency_ms=5_000,
        )

        db.execute = AsyncMock(return_value=_mock_execute_returning(existing))

        await record_clip_metrics(
            db,
            str(session_id),
            [
                _telemetry(latency_ms=1_000, bytes_uploaded=500_000),
                _telemetry(latency_ms=2_000, bytes_uploaded=500_000, degraded_to_frame=True),
            ],
        )

        # No new row inserted — updated in place.
        db.add.assert_not_called()
        assert existing.clip_count == 2
        assert existing.clip_bytes_uploaded == 1_000_000
        assert existing.clip_avg_latency_ms == 1_500
        assert existing.clip_degraded_to_frame_count == 1
        # Pre-existing field untouched.
        assert existing.stage1_latency_ms == 5_000
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_session_row_skips_upsert(self, caplog) -> None:
        """If neither a metrics row nor a session row exists, log INFO
        and return — never crash."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_returning(None),
                _mock_execute_returning(None),
            ]
        )

        with caplog.at_level(logging.INFO, logger="aurion.vision.clip_metrics"):
            await record_clip_metrics(
                db, str(uuid.uuid4()), [_telemetry()]
            )
        db.add.assert_not_called()
        assert any(
            "no session row" in rec.message for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_db_failure_is_swallowed(self, caplog) -> None:
        """Passive metrics must not break Stage 2. A db error is logged
        WARNING and the function returns normally."""
        db = _mock_db()
        db.execute = AsyncMock(side_effect=RuntimeError("connection refused"))

        with caplog.at_level(logging.WARNING, logger="aurion.vision.clip_metrics"):
            await record_clip_metrics(
                db, str(uuid.uuid4()), [_telemetry()]
            )
        assert any(
            "Failed to record clip metrics" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_phi_scan_emitter_log_path(self, caplog) -> None:
        """AC-7: no patient identifiers in the emitter logging path.

        The logger should emit session-prefix (8 chars), counts, ms, and
        micros — never an s3_key, a clinician name, or a free-text
        clinical string.
        """
        db = _mock_db()
        session_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        existing = PilotMetricsModel(
            session_id=session_id,
            clinician_id=clinician_id,
            specialty="orthopedic_surgery",
        )
        db.execute = AsyncMock(return_value=_mock_execute_returning(existing))

        with caplog.at_level(logging.INFO, logger="aurion.vision.clip_metrics"):
            await record_clip_metrics(
                db,
                str(session_id),
                [_telemetry()],
            )

        emit_logs = [r.message for r in caplog.records]
        joined = " ".join(emit_logs)
        # No full session UUIDs — only 8-char prefix.
        assert str(session_id) not in joined, (
            "Full session UUID should not appear in emitter log"
        )
        # No s3_keys ("clips/" prefix is the canonical clip object key).
        assert "clips/" not in joined
        # Log should reference the 8-char prefix.
        assert any(
            re.search(r"session=[0-9a-f]{8}\b", line) for line in emit_logs
        ), f"Expected session-prefix log line; got {emit_logs}"
