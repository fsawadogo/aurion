"""Provider usage service — per-call telemetry persistence + aggregation
(issue #73 foundation).

Trigger sites call ``record(...)``; the dashboard endpoint calls
``aggregate(...)``. Best-effort: callers should wrap ``record`` in a
try/except so a telemetry-DB hiccup never breaks the audited
provider-call path it sits next to (same pattern as ``alerts``).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.database import async_session_factory
from app.core.models import ProviderUsageModel

logger = logging.getLogger("aurion.providers.usage")


@dataclass(frozen=True)
class UsageTotals:
    """Window-wide rollup."""

    call_count: int
    success_count: int
    failure_count: int
    fallback_count: int
    avg_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


@dataclass(frozen=True)
class ComparisonDelta:
    """Pre-computed ``b - a`` deltas. Positive means b is higher."""

    avg_latency_ms: float
    success_rate: float
    fallback_rate: float


@dataclass(frozen=True)
class ComparisonResult:
    """Side-by-side comparison of two providers over a window."""

    provider_type: str
    a: str
    b: str
    a_rollup: "ProviderRollup | None"
    b_rollup: "ProviderRollup | None"
    delta: ComparisonDelta


@dataclass(frozen=True)
class ProviderRollup:
    """Per-(provider_type, provider_name) rollup."""

    provider_type: str
    provider_name: str
    call_count: int
    success_count: int
    failure_count: int
    fallback_count: int
    avg_latency_ms: float
    success_rate: float
    fallback_rate: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class ProviderUsageService:
    """Thin service around the ``provider_usage`` table."""

    async def record(
        self,
        db: AsyncSession,
        *,
        provider_type: str,
        provider_name: str,
        operation: str,
        latency_ms: int,
        success: bool,
        fallback_used: bool = False,
        model_name: str | None = None,
        session_id: uuid.UUID | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> uuid.UUID:
        """Persist one row; return its id."""
        record = ProviderUsageModel(
            id=uuid.uuid4(),
            provider_type=provider_type,
            provider_name=provider_name,
            model_name=model_name,
            operation=operation,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            success=success,
            fallback_used=fallback_used,
            created_at=utcnow(),
        )
        db.add(record)
        await db.flush()
        return record.id

    async def aggregate(
        self,
        db: AsyncSession,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        provider_type: str | None = None,
    ) -> tuple[UsageTotals, list[ProviderRollup]]:
        """Return ``(totals, by_provider)`` over the window."""

        def _apply_filters(stmt):
            if since is not None:
                stmt = stmt.where(ProviderUsageModel.created_at >= since)
            if until is not None:
                stmt = stmt.where(ProviderUsageModel.created_at <= until)
            if provider_type is not None:
                stmt = stmt.where(
                    ProviderUsageModel.provider_type == provider_type
                )
            return stmt

        # ── Totals ────────────────────────────────────────────────────
        totals_stmt = _apply_filters(
            select(
                func.count(ProviderUsageModel.id),
                func.count().filter(ProviderUsageModel.success.is_(True)),
                func.count().filter(ProviderUsageModel.success.is_(False)),
                func.count().filter(ProviderUsageModel.fallback_used.is_(True)),
                func.coalesce(func.avg(ProviderUsageModel.latency_ms), 0.0),
                func.coalesce(func.sum(ProviderUsageModel.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsageModel.output_tokens), 0),
                func.coalesce(func.sum(ProviderUsageModel.cost_usd), 0.0),
            )
        )
        row = (await db.execute(totals_stmt)).one()
        totals = UsageTotals(
            call_count=int(row[0] or 0),
            success_count=int(row[1] or 0),
            failure_count=int(row[2] or 0),
            fallback_count=int(row[3] or 0),
            avg_latency_ms=float(row[4] or 0.0),
            total_input_tokens=int(row[5] or 0),
            total_output_tokens=int(row[6] or 0),
            total_cost_usd=float(row[7] or 0.0),
        )

        # ── Per-provider rollup ───────────────────────────────────────
        per_stmt = _apply_filters(
            select(
                ProviderUsageModel.provider_type,
                ProviderUsageModel.provider_name,
                func.count(ProviderUsageModel.id),
                func.count().filter(ProviderUsageModel.success.is_(True)),
                func.count().filter(ProviderUsageModel.success.is_(False)),
                func.count().filter(ProviderUsageModel.fallback_used.is_(True)),
                func.coalesce(func.avg(ProviderUsageModel.latency_ms), 0.0),
                func.coalesce(func.sum(ProviderUsageModel.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsageModel.output_tokens), 0),
                func.coalesce(func.sum(ProviderUsageModel.cost_usd), 0.0),
            )
        ).group_by(
            ProviderUsageModel.provider_type, ProviderUsageModel.provider_name
        ).order_by(
            ProviderUsageModel.provider_type, ProviderUsageModel.provider_name
        )
        by_provider: list[ProviderRollup] = []
        for r in (await db.execute(per_stmt)).all():
            count = int(r[2] or 0)
            success = int(r[3] or 0)
            fallback = int(r[5] or 0)
            by_provider.append(
                ProviderRollup(
                    provider_type=r[0],
                    provider_name=r[1],
                    call_count=count,
                    success_count=success,
                    failure_count=int(r[4] or 0),
                    fallback_count=fallback,
                    avg_latency_ms=float(r[6] or 0.0),
                    success_rate=(success / count) if count else 0.0,
                    fallback_rate=(fallback / count) if count else 0.0,
                    total_input_tokens=int(r[7] or 0),
                    total_output_tokens=int(r[8] or 0),
                    total_cost_usd=float(r[9] or 0.0),
                )
            )
        return totals, by_provider

    async def compare(
        self,
        db: AsyncSession,
        *,
        provider_type: str,
        a: str,
        b: str,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ComparisonResult:
        """Side-by-side comparison of two providers over a window (#74).

        Reuses ``aggregate(...)``: one rollup per provider, then computes
        ``b - a`` deltas. A provider with zero calls in the window
        produces ``None`` for its rollup (UI shows "no data"); the delta
        falls back to the present rollup's values for legibility.
        """
        _, by_a = await self.aggregate(
            db, since=since, until=until, provider_type=provider_type
        )
        a_rollup = next(
            (r for r in by_a if r.provider_name == a), None
        )
        # Second call — we only need provider b's rollup, but reusing
        # aggregate keeps a single source of truth for the rollup shape.
        _, by_b = await self.aggregate(
            db, since=since, until=until, provider_type=provider_type
        )
        b_rollup = next(
            (r for r in by_b if r.provider_name == b), None
        )

        a_lat = a_rollup.avg_latency_ms if a_rollup else 0.0
        b_lat = b_rollup.avg_latency_ms if b_rollup else 0.0
        a_succ = a_rollup.success_rate if a_rollup else 0.0
        b_succ = b_rollup.success_rate if b_rollup else 0.0
        a_fb = a_rollup.fallback_rate if a_rollup else 0.0
        b_fb = b_rollup.fallback_rate if b_rollup else 0.0

        return ComparisonResult(
            provider_type=provider_type,
            a=a,
            b=b,
            a_rollup=a_rollup,
            b_rollup=b_rollup,
            delta=ComparisonDelta(
                avg_latency_ms=b_lat - a_lat,
                success_rate=b_succ - a_succ,
                fallback_rate=b_fb - a_fb,
            ),
        )


_INSTANCE: ProviderUsageService | None = None


def get_provider_usage_service() -> ProviderUsageService:
    """Lazy singleton — mirrors the alerts / audit_log factory shape."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProviderUsageService()
    return _INSTANCE


def _coerce_session_id(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Coerce to UUID, returning None for anything that doesn't parse —
    so trigger sites can pass ``frame.session_id`` (which may be a
    legacy / synthetic identifier) without raising. The telemetry row
    just records null for that case."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def try_record_provider_usage(
    *,
    provider_type: str,
    provider_name: str,
    operation: str,
    latency_ms: int,
    success: bool,
    fallback_used: bool = False,
    model_name: str | None = None,
    session_id: str | uuid.UUID | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Fire-and-forget telemetry write for trigger sites without an
    existing AsyncSession (caption_frames, transcribe_audio, …).

    Mirrors ``try_publish_alert`` in alerts: opens a short-lived
    session, commits, and swallows any error so a telemetry-DB hiccup
    never alters the audited code path it sits next to.

    Callers that already have a session should call
    ``get_provider_usage_service().record(db, ...)`` directly so the
    row lands in the same transaction.
    """
    try:
        async with async_session_factory() as db:
            await get_provider_usage_service().record(
                db,
                provider_type=provider_type,
                provider_name=provider_name,
                operation=operation,
                latency_ms=latency_ms,
                success=success,
                fallback_used=fallback_used,
                model_name=model_name,
                session_id=_coerce_session_id(session_id),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — best-effort by design
        logger.warning(
            "provider_usage record failed: type=%s op=%s",
            provider_type,
            operation,
            exc_info=True,
        )
