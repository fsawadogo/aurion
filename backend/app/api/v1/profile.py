"""Profile API routes — physician preferences and practice configuration.

Endpoints are accessible to any authenticated user for their own profile.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.profile.service import (
    get_or_create_profile,
    get_preferred_template_objects,
    update_profile,
)

router = APIRouter(prefix="/profile", tags=["profile"])


# ── Schemas ─────────────────────────────────────────────────────────────────


class ProfileResponse(BaseModel):
    clinician_id: str
    display_name: str
    practice_type: Optional[str] = None
    primary_specialty: str
    preferred_templates: list[str]
    consultation_types: list[str]
    allied_health_team: list[dict] = []
    output_language: str
    # Portal/iOS chrome preferences (Phase A1). Distinct from
    # `output_language`: a physician may dictate in English and read
    # the chrome in French. `ui_theme` is "system" / "light" / "dark".
    ui_theme: str = "system"
    ui_language: str = "en"
    auto_upload: bool = True
    retention_days: int = 7
    consent_reprompt: str = "every_session"

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    practice_type: Optional[str] = None
    primary_specialty: Optional[str] = None
    preferred_templates: Optional[list[str]] = None
    consultation_types: Optional[list[str]] = None
    allied_health_team: Optional[list[dict]] = None
    output_language: Optional[str] = None
    ui_theme: Optional[str] = None
    ui_language: Optional[str] = None
    auto_upload: Optional[bool] = None
    retention_days: Optional[int] = None
    consent_reprompt: Optional[str] = None

    @field_validator("ui_theme")
    @classmethod
    def _validate_ui_theme(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in {"system", "light", "dark"}:
            raise ValueError("ui_theme must be one of: system, light, dark")
        return v

    @field_validator("ui_language")
    @classmethod
    def _validate_ui_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Locked to en/fr today; widen here when iOS/portal locales grow.
        # The column itself holds up to 16 chars so IETF tags like
        # "fr-CA" forward-compat without a migration.
        if v not in {"en", "fr"}:
            raise ValueError("ui_language must be one of: en, fr")
        return v


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's profile. Auto-creates with defaults on first call."""
    profile = await get_or_create_profile(
        db, clinician_id=user.user_id, display_name=user.email
    )
    return _to_response(profile)


@router.put("", response_model=ProfileResponse)
async def update_profile_route(
    body: UpdateProfileRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's profile fields."""
    # Ensure profile exists
    await get_or_create_profile(db, clinician_id=user.user_id, display_name=user.email)

    updates = body.model_dump(exclude_none=True)
    profile = await update_profile(db, clinician_id=user.user_id, updates=updates)
    return _to_response(profile)


@router.get("/templates")
async def get_profile_templates(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's preferred templates as full template objects."""
    templates = await get_preferred_template_objects(db, clinician_id=user.user_id)
    return templates


# ── Helpers ─────────────────────────────────────────────────────────────────


def _to_response(profile) -> ProfileResponse:
    return ProfileResponse(
        clinician_id=str(profile.clinician_id),
        display_name=profile.display_name,
        practice_type=profile.practice_type,
        primary_specialty=profile.primary_specialty,
        preferred_templates=json.loads(profile.preferred_templates),
        consultation_types=json.loads(profile.consultation_types),
        allied_health_team=json.loads(profile.allied_health_team),
        output_language=profile.output_language,
        ui_theme=getattr(profile, "ui_theme", "system"),
        ui_language=getattr(profile, "ui_language", "en"),
        auto_upload=getattr(profile, "auto_upload", True),
        retention_days=getattr(profile, "retention_days", 7),
        consent_reprompt=getattr(profile, "consent_reprompt", "every_session"),
    )
