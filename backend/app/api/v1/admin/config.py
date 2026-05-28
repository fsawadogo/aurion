"""Runtime AI-provider override endpoints — ADMIN or COMPLIANCE_OFFICER.

Lets an operator pin the active transcription/note_generation/vision
provider at runtime without a redeploy and without granting the app any
new AWS/IAM permission. The override is persisted in the
``provider_overrides`` table and mirrored into the registry's in-memory
cache; precedence is:

    per-call override  >  DB override store  >  AppConfig value

The serving task reflects a write immediately (``set_cached`` /
``clear_cached``); other ECS tasks converge within ~10s via the
override poller.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import ProviderOverrideModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_overrides import (
    clear_cached,
    get_override,
    set_cached,
)
from app.modules.config.schema import (
    NoteGenerationProviderKey,
    TranscriptionProviderKey,
    VisionProviderKey,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Maps each provider type to its validating enum. The keys here are the
# authoritative set of valid ``provider_type`` path values.
_PROVIDER_ENUMS: dict[str, type] = {
    "transcription": TranscriptionProviderKey,
    "note_generation": NoteGenerationProviderKey,
    "vision": VisionProviderKey,
}

# Non-session admin action — the audit log keys on session_id, so we use
# the same "system" sentinel that admin/users.py uses for USER_CREATED /
# USER_UPDATED (non-session admin events).
_AUDIT_SENTINEL = "system"


# ── Schemas ─────────────────────────────────────────────────────────────────


class SetProviderOverrideRequest(BaseModel):
    value: str
    reason: Optional[str] = None


class ProviderEffective(BaseModel):
    provider_type: str
    appconfig_value: str
    override_value: Optional[str]
    effective_value: str


class ProvidersOverviewResponse(BaseModel):
    providers: list[ProviderEffective]


# ── Helpers ───────────────────────────────────────────────────────────────


def _appconfig_value(provider_type: str) -> str:
    providers = get_config().providers
    raw = getattr(providers, provider_type)
    # Provider keys are str-enums; ``.value`` is the wire string.
    return raw.value if hasattr(raw, "value") else str(raw)


def _build_overview() -> ProvidersOverviewResponse:
    rows: list[ProviderEffective] = []
    for ptype in _PROVIDER_ENUMS:
        appconfig_value = _appconfig_value(ptype)
        override_value = get_override(ptype)
        rows.append(
            ProviderEffective(
                provider_type=ptype,
                appconfig_value=appconfig_value,
                override_value=override_value,
                effective_value=override_value or appconfig_value,
            )
        )
    return ProvidersOverviewResponse(providers=rows)


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/providers", response_model=ProvidersOverviewResponse)
async def get_providers(
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
):
    """Show, per provider type, the AppConfig value, any active override,
    and the resolved effective value. ADMIN or COMPLIANCE_OFFICER."""
    return _build_overview()


@router.put("/providers/{provider_type}", response_model=ProvidersOverviewResponse)
async def set_provider_override(
    provider_type: str,
    body: SetProviderOverrideRequest,
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Pin the active provider for ``provider_type`` at runtime.

    Validates the path against the known provider types and the body
    ``value`` against that provider's enum, upserts the override row,
    updates the in-memory cache immediately, and audits the change.
    ADMIN or COMPLIANCE_OFFICER.
    """
    enum_cls = _PROVIDER_ENUMS.get(provider_type)
    if enum_cls is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid provider_type '{provider_type}'. "
                f"Must be one of: {', '.join(_PROVIDER_ENUMS)}"
            ),
        )

    try:
        validated = enum_cls(body.value)
    except ValueError:
        valid = ", ".join(m.value for m in enum_cls)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid value '{body.value}' for {provider_type}. "
                f"Must be one of: {valid}"
            ),
        )

    value = validated.value

    # Upsert the override row (one row per provider type).
    row = await db.get(ProviderOverrideModel, provider_type)
    if row is None:
        row = ProviderOverrideModel(
            provider_type=provider_type,
            provider_value=value,
            set_by=user.user_id,
            reason=body.reason,
        )
        db.add(row)
    else:
        row.provider_value = value
        row.set_by = user.user_id
        row.reason = body.reason
    await db.flush()

    # Reflect the change in the serving task immediately; other tasks
    # converge within ~10s on the next override poll.
    set_cached(provider_type, value)

    await write_audit(
        _AUDIT_SENTINEL,
        AuditEventType.PROVIDER_OVERRIDE_SET,
        changed_by=str(user.user_id),
        provider_type=provider_type,
        new_provider=value,
        reason=body.reason or "",
    )

    return _build_overview()


@router.delete("/providers/{provider_type}", response_model=ProvidersOverviewResponse)
async def clear_provider_override(
    provider_type: str,
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Remove any runtime override for ``provider_type`` — resolution
    falls back to AppConfig. ADMIN or COMPLIANCE_OFFICER."""
    if provider_type not in _PROVIDER_ENUMS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid provider_type '{provider_type}'. "
                f"Must be one of: {', '.join(_PROVIDER_ENUMS)}"
            ),
        )

    row = await db.get(ProviderOverrideModel, provider_type)
    old_provider = row.provider_value if row is not None else ""
    if row is not None:
        await db.delete(row)
        await db.flush()

    clear_cached(provider_type)

    await write_audit(
        _AUDIT_SENTINEL,
        AuditEventType.PROVIDER_OVERRIDE_CLEARED,
        changed_by=str(user.user_id),
        provider_type=provider_type,
        old_provider=old_provider,
    )

    return _build_overview()
