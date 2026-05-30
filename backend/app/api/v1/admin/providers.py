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
from app.modules.providers.usage_service import (
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
