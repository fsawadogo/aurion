"""Provider cost & usage dashboard endpoint (issue #73 foundation).

Returns an aggregated rollup of provider calls over a date range so the
admin UI / CTO can compare providers on call count, success rate, fallback
rate, and latency. Token / cost totals roll up as well but only fill in
once the base.py provider-interface refactor surfaces ``usage`` per call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.eval.repository import aggregate_scores_by_provider
from app.modules.providers.usage_service import (
    ComparisonResult,
    ProviderUsageService,
    get_provider_usage_service,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class TotalsResponse(BaseModel):
    call_count: int
    success_count: int
    failure_count: int
    fallback_count: int
    avg_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class ProviderRollupResponse(BaseModel):
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


class ProviderUsageResponse(BaseModel):
    since: datetime | None
    until: datetime | None
    provider_type: str | None
    totals: TotalsResponse
    by_provider: list[ProviderRollupResponse]


class ComparisonDeltaResponse(BaseModel):
    avg_latency_ms: float
    success_rate: float
    fallback_rate: float


class ProviderCompareResponse(BaseModel):
    provider_type: str
    a: str
    b: str
    since: datetime | None
    until: datetime | None
    a_rollup: ProviderRollupResponse | None
    b_rollup: ProviderRollupResponse | None
    delta: ComparisonDeltaResponse


def _rollup_to_response(rollup) -> ProviderRollupResponse | None:
    if rollup is None:
        return None
    return ProviderRollupResponse(**rollup.__dict__)


@router.get("/providers/compare", response_model=ProviderCompareResponse)
async def compare_providers(
    a: str = Query(..., min_length=1, max_length=64, description="Provider A name."),
    b: str = Query(..., min_length=1, max_length=64, description="Provider B name."),
    provider_type: str = Query(
        ...,
        pattern="^(transcription|note_generation|vision)$",
        description="Provider type to compare within.",
    ),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
    db: AsyncSession = Depends(get_db),
    service: ProviderUsageService = Depends(get_provider_usage_service),
) -> ProviderCompareResponse:
    """Side-by-side comparison of two providers over a window.

    A provider with zero calls returns ``null`` for its rollup; the delta
    block is still present (deltas use 0.0 for absent sides).
    """
    result: ComparisonResult = await service.compare(
        db,
        provider_type=provider_type,
        a=a,
        b=b,
        since=since,
        until=until,
    )
    return ProviderCompareResponse(
        provider_type=result.provider_type,
        a=result.a,
        b=result.b,
        since=since,
        until=until,
        a_rollup=_rollup_to_response(result.a_rollup),
        b_rollup=_rollup_to_response(result.b_rollup),
        delta=ComparisonDeltaResponse(**result.delta.__dict__),
    )


@router.get("/providers/usage", response_model=ProviderUsageResponse)
async def provider_usage(
    since: Optional[datetime] = Query(
        None, description="ISO timestamp lower bound (inclusive)."
    ),
    until: Optional[datetime] = Query(
        None, description="ISO timestamp upper bound (inclusive)."
    ),
    provider_type: Optional[str] = Query(
        None,
        pattern="^(transcription|note_generation|vision)$",
        description="Filter to a single provider type.",
    ),
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
    db: AsyncSession = Depends(get_db),
    service: ProviderUsageService = Depends(get_provider_usage_service),
) -> ProviderUsageResponse:
    """Aggregated provider call telemetry over the given window."""
    totals, by_provider = await service.aggregate(
        db, since=since, until=until, provider_type=provider_type
    )
    return ProviderUsageResponse(
        since=since,
        until=until,
        provider_type=provider_type,
        totals=TotalsResponse(**totals.__dict__),
        by_provider=[ProviderRollupResponse(**r.__dict__) for r in by_provider],
    )


# ── Quality A-B compare (#74 / OV-3) ─────────────────────────────────────────


class ProviderQualityRow(BaseModel):
    provider_name: str
    scored_sessions: int
    avg_overall: float | None
    avg_transcript_accuracy: float | None
    avg_citation_correctness: float | None
    avg_descriptive_mode_compliance: float | None
    avg_hallucination_count: float | None


class ProviderQualityCompareResponse(BaseModel):
    since: datetime | None
    until: datetime | None
    providers: list[ProviderQualityRow]


@router.get(
    "/providers/compare-quality", response_model=ProviderQualityCompareResponse
)
async def compare_provider_quality(
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    user: CurrentUser = Depends(require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ProviderQualityCompareResponse:
    """Per-provider quality averages from eval scores (#74).

    Pre-attribution scores (provider unknown) are excluded; counts are
    surfaced so a reviewer can judge sample size honestly — at pilot N,
    differences are directional, not significant, and the UI labels them
    as such. EVAL_TEAM + ADMIN (the roles that see the underlying scores).
    """
    rows = await aggregate_scores_by_provider(db, since=since, until=until)
    return ProviderQualityCompareResponse(
        since=since,
        until=until,
        providers=[ProviderQualityRow(**r) for r in rows],
    )
