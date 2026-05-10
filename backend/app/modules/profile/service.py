"""Physician profile CRUD service.

Manages per-clinician preferences: practice type, primary specialty,
preferred templates, consultation types, and output language.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PhysicianProfileModel
from app.modules.note_gen.service import get_template, load_templates

logger = logging.getLogger("aurion.profile")


async def get_or_create_profile(
    db: AsyncSession,
    clinician_id: uuid.UUID,
    display_name: str = "",
) -> PhysicianProfileModel:
    """Fetch the clinician's profile, creating one with defaults if it doesn't exist."""
    result = await db.execute(
        select(PhysicianProfileModel).where(
            PhysicianProfileModel.clinician_id == clinician_id
        )
    )
    profile = result.scalar_one_or_none()

    if profile:
        return profile

    profile = PhysicianProfileModel(
        clinician_id=clinician_id,
        display_name=display_name,
        primary_specialty="general",
        preferred_templates=json.dumps(list(load_templates().keys())),
        consultation_types=json.dumps(["new_patient", "follow_up"]),
    )
    db.add(profile)
    await db.flush()
    logger.info("Created physician profile for clinician=%s", clinician_id)
    return profile


async def update_profile(
    db: AsyncSession,
    clinician_id: uuid.UUID,
    updates: dict,
) -> PhysicianProfileModel:
    """Update profile fields. Only updates provided (non-None) fields."""
    result = await db.execute(
        select(PhysicianProfileModel).where(
            PhysicianProfileModel.clinician_id == clinician_id
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise ValueError(f"No profile found for clinician {clinician_id}")

    if "display_name" in updates:
        profile.display_name = updates["display_name"]
    if "practice_type" in updates:
        profile.practice_type = updates["practice_type"]
    if "primary_specialty" in updates:
        profile.primary_specialty = updates["primary_specialty"]
    if "preferred_templates" in updates:
        profile.preferred_templates = json.dumps(updates["preferred_templates"])
    if "consultation_types" in updates:
        profile.consultation_types = json.dumps(updates["consultation_types"])
    if "allied_health_team" in updates:
        team = updates["allied_health_team"]
        if len(team) > 2:
            raise ValueError("Maximum 2 allied health team members allowed")
        profile.allied_health_team = json.dumps(team)
    if "output_language" in updates:
        profile.output_language = updates["output_language"]
    if "auto_upload" in updates:
        profile.auto_upload = bool(updates["auto_upload"])
    if "retention_days" in updates:
        # Clamp to the same range the iOS stepper enforces — keeps the
        # local-retention contract honest if a client sends a bogus value.
        days = int(updates["retention_days"])
        profile.retention_days = max(1, min(30, days))
    if "consent_reprompt" in updates:
        cadence = updates["consent_reprompt"]
        if cadence in ("every_session", "daily", "weekly"):
            profile.consent_reprompt = cadence

    await db.flush()
    logger.info("Updated physician profile for clinician=%s", clinician_id)
    return profile


async def get_preferred_template_objects(
    db: AsyncSession,
    clinician_id: uuid.UUID,
) -> list[dict]:
    """Return the clinician's preferred templates as full template objects."""
    result = await db.execute(
        select(PhysicianProfileModel).where(
            PhysicianProfileModel.clinician_id == clinician_id
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        # Return all templates as default
        templates = load_templates()
        return [t.model_dump() for t in templates.values()]

    preferred_keys = json.loads(profile.preferred_templates)
    result_templates = []
    for key in preferred_keys:
        try:
            template = get_template(key)
            result_templates.append(template.model_dump())
        except ValueError:
            continue

    return result_templates
