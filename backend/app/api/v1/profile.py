"""Profile API routes — physician preferences and practice configuration.

Endpoints are accessible to any authenticated user for their own profile.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.text_validation import validate_user_text
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.profile.service import (
    get_or_create_profile,
    get_preferred_template_objects,
    update_profile,
)

router = APIRouter(prefix="/profile", tags=["profile"])

# Profile-scoped events aren't tied to a clinical session. Same synthetic
# anchor that the auth / MFA / prompt-overlay paths use so the row stays
# out of any real session's history while remaining queryable on
# (event_type, actor_id).
_PROFILE_AUDIT_SESSION = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Canonical default consultation-type keys. Anything not in this set on
# the consultation_types list is treated as a clinician-authored custom
# label. Kept here (not imported from another module) because the iOS and
# portal clients also hard-code this list — duplicating the four keys is
# cheaper than adding a separate config table for what will always be a
# short, stable set of defaults.
_DEFAULT_CONSULTATION_TYPES = frozenset(
    {"new_patient", "follow_up", "pre_op", "post_op"}
)

# Hard caps enforced server-side. Mirrors the iOS-side / portal-side
# limits so a client that bypasses its own gates still can't write
# pathological data. 20 customs is a soft pilot limit (Dr. Marie at #259
# expects single-digit counts); the 60-char cap is generous enough to
# carry "Lower-Limb New Patient" while bounding the audit risk.
_MAX_CUSTOM_CONSULTATION_TYPES = 20
_MAX_CONSULTATION_TYPE_LEN = 60


def _validate_consultation_type(value: str) -> str:
    """Validate one custom consultation-type label.

    Returns the stripped value. Raises ``ValueError`` on any gate
    failure. Mirrors the iOS-side helper + the web-side
    ``validateConsultationType``. NEVER includes the rejected value in
    the error.

    Posture: SSN / email / 60-char cap gates are on. The full-name
    gate is OFF here — Dr. Marie's "LL new pt" / "LL fu" and Dr. Perry's
    "Breast visit" are multi-word labels by design and the patient-
    identifier-style full-name heuristic would reject them. The
    proper-noun-shape gate below catches the residual "two capitalized
    word tokens" pattern (e.g. "Jane Doe") without rejecting legitimate
    multi-word shorthand.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("consultation type is empty")
    try:
        validate_user_text(
            stripped,
            max_length=_MAX_CONSULTATION_TYPE_LEN,
            reject_full_name=False,
        )
    except ValueError as exc:
        # Same shape as `_check_identifier_format` — surface the noun
        # the caller's catalog expects without re-implementing the
        # underlying gates.
        msg = str(exc).replace("text", "consultation type", 1)
        raise ValueError(msg) from None
    if _looks_like_proper_noun_pair(stripped):
        raise ValueError("consultation type looks like a full name")
    return stripped


def _looks_like_proper_noun_pair(value: str) -> bool:
    """Cheap "two-capitalized-words" heuristic.

    Catches the obvious "Jane Doe" / "Marie Gdalevitch" shape while
    leaving the typical clinician shorthand alone:
      * "LL fu"      → second token starts lowercase → OK
      * "Breast visit" → second token starts lowercase → OK
      * "Pre-op"     → single token → OK
      * "Jane Doe"   → both tokens start capital, all alpha → REJECT
      * "Marie M Gdalevitch" → all three tokens start capital → REJECT
    """
    tokens = [t for t in value.split() if t]
    if len(tokens) < 2:
        return False
    for tok in tokens:
        first = tok[0]
        # Each token must start with an uppercase letter and be entirely
        # alphabetic (letters + apostrophes / hyphens permitted) for the
        # pattern to trip. Anything with a digit or other punctuation
        # is treated as a clinician shorthand.
        if not first.isupper():
            return False
        if not all(c.isalpha() or c in {"'", "-", "’"} for c in tok):
            return False
    return True


def _split_defaults_customs(types: list[str]) -> tuple[set[str], set[str]]:
    """Partition a consultation-types list into (defaults, customs)."""
    defaults = {t for t in types if t in _DEFAULT_CONSULTATION_TYPES}
    customs = {t for t in types if t not in _DEFAULT_CONSULTATION_TYPES}
    return defaults, customs


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
    # `hide_input_in_errors=True` is load-bearing here for
    # `consultation_types`: a clinician's custom label could in the worst
    # case carry a name even after the format gates, and Pydantic's
    # default `ValidationError` echoes the rejected `input_value`. We
    # want zero chance of that landing in 422 bodies or Sentry. Same
    # posture `ExternalReferenceIdRequest` in sessions.py takes.
    model_config = ConfigDict(hide_input_in_errors=True)

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

    @field_validator("consultation_types")
    @classmethod
    def _validate_consultation_types(
        cls, v: Optional[list[str]]
    ) -> Optional[list[str]]:
        """Allow the 4 default keys as-is; gate every custom label.

        Custom labels (anything not in `_DEFAULT_CONSULTATION_TYPES`)
        go through `_validate_consultation_type`. The stripped /
        canonical form is what we persist — leading/trailing whitespace
        on input is forgiven so a clinician's "Breast visit " round-
        trips as "Breast visit".

        The 20-custom soft cap is enforced here so the API rejects
        before any audit row is written.
        """
        if v is None:
            return v
        cleaned: list[str] = []
        seen: set[str] = set()
        custom_count = 0
        for item in v:
            if not isinstance(item, str):
                raise ValueError("consultation type must be a string")
            if item in _DEFAULT_CONSULTATION_TYPES:
                # Defaults round-trip as the exact canonical key.
                canonical = item
            else:
                canonical = _validate_consultation_type(item)
                custom_count += 1
                if custom_count > _MAX_CUSTOM_CONSULTATION_TYPES:
                    raise ValueError(
                        f"max {_MAX_CUSTOM_CONSULTATION_TYPES} custom "
                        "consultation types"
                    )
            # De-dup case-sensitively. Two customs that differ only in
            # case ("LL fu" vs "ll fu") are treated as distinct by
            # design — physicians can choose their own casing.
            if canonical in seen:
                continue
            seen.add(canonical)
            cleaned.append(canonical)
        return cleaned


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
    # Ensure profile exists. Snapshot the pre-update team list so the
    # audit-row count delta below reflects the actual change, not the
    # post-write state.
    existing = await get_or_create_profile(
        db, clinician_id=user.user_id, display_name=user.email
    )
    team_before_count: Optional[int] = None
    if body.allied_health_team is not None:
        try:
            team_before_count = len(json.loads(existing.allied_health_team))
        except (TypeError, ValueError):
            # Defensive — the column is `NOT NULL DEFAULT "[]"` so this
            # should never trip, but a bad legacy row shouldn't crash
            # the update path. Fall back to "no signal" and skip the
            # emit; the change still goes through.
            team_before_count = None

    # GH-259 — snapshot the pre-update consultation types list to compute
    # the count deltas the audit row carries. Like `team_before_count`
    # above, a parse failure on a legacy row falls back to "no signal"
    # rather than crashing the update path.
    types_before: Optional[list[str]] = None
    if body.consultation_types is not None:
        try:
            raw = json.loads(existing.consultation_types)
            if isinstance(raw, list):
                types_before = [t for t in raw if isinstance(t, str)]
        except (TypeError, ValueError):
            types_before = None

    updates = body.model_dump(exclude_none=True)
    profile = await update_profile(db, clinician_id=user.user_id, updates=updates)

    # GH-260 — emit TEAM_MEMBERS_UPDATED only when the count actually
    # changed. Same-content edits (re-order, rename in place) skip the
    # audit emit so the trail stays meaningful instead of noisy. Names
    # are deliberately NOT in the kwargs; see the docstring on the enum
    # member for the PHI rationale.
    if body.allied_health_team is not None and team_before_count is not None:
        team_after_count = len(body.allied_health_team)
        if team_before_count != team_after_count:
            await write_audit(
                _PROFILE_AUDIT_SESSION,
                AuditEventType.TEAM_MEMBERS_UPDATED,
                actor_id=str(user.user_id),
                members_count_before=team_before_count,
                members_count_after=team_after_count,
            )

    # GH-259 — emit PROFILE_CONSULTATION_TYPES_UPDATED with counts only
    # when the canonical list actually changed. Same-list edits skip the
    # emit so the trail stays meaningful. The four count deltas
    # (defaults/customs × added/removed) let the post-pilot review
    # answer "did clinicians use the feature?" without any labels
    # landing in the audit row. See the kwarg whitelist in
    # `audit_events.py::PROFILE_CONSULTATION_TYPES_UPDATED` for the
    # PHI-safety contract.
    if body.consultation_types is not None and types_before is not None:
        before = list(types_before)
        # `_validate_consultation_types` already de-duplicated, stripped,
        # and gated `body.consultation_types`. We re-read off the field
        # rather than the dumped `updates` dict so the pydantic-validated
        # form is what we diff against.
        after_canonical = body.consultation_types
        b_defaults, b_customs = _split_defaults_customs(before)
        a_defaults, a_customs = _split_defaults_customs(after_canonical)
        defaults_added = len(a_defaults - b_defaults)
        defaults_removed = len(b_defaults - a_defaults)
        customs_added = len(a_customs - b_customs)
        customs_removed = len(b_customs - a_customs)
        if (
            defaults_added
            or defaults_removed
            or customs_added
            or customs_removed
        ):
            await write_audit(
                _PROFILE_AUDIT_SESSION,
                AuditEventType.PROFILE_CONSULTATION_TYPES_UPDATED,
                actor_id=str(user.user_id),
                count_before=len(before),
                count_after=len(after_canonical),
                defaults_added=defaults_added,
                defaults_removed=defaults_removed,
                customs_added=customs_added,
                customs_removed=customs_removed,
            )

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
