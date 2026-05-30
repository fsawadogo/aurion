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


_INSTANCE: ProviderUsageService | None = None


def get_provider_usage_service() -> ProviderUsageService:
    """Lazy singleton — mirrors the alerts / audit_log factory shape."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProviderUsageService()
    return _INSTANCE
