"""ADMIN-only feature-flag toggle endpoints.

Narrow admin surface for one job: let an ADMIN flip the four card-
visibility flags (``orders_card_enabled``, ``coding_card_enabled``,
``patient_summary_card_enabled``, ``emr_writeback_card_enabled``)
without redeploying or shelling out to the AWS CLI.

This endpoint pushes a new AppConfig hosted-configuration-version and
starts a deployment against the configured deployment strategy. The
write goes through the same boto3 AppConfig client the rest of the
backend uses for reads — schema validation still happens server-side
(the Terraform-managed JSON Schema validator on the configuration
profile is the gate). If the new content fails that schema, AWS rejects
the create-hosted-version call and we surface a 400 with the validator
message.

See the comment in ``infrastructure/appconfig.tf`` for the
``InvalidSignatureException`` em-dash bug that's the reason Terraform
no longer manages the hosted-version + deployment resources — this
endpoint is the programmatic-but-still-CLI-equivalent workflow.

Audit: every successful write emits
``AuditEventType.FEATURE_FLAGS_UPDATED`` carrying ONLY the names of
the fields that changed plus the new hosted-version number. The values
are not in the audit row — they're config metadata and AppConfig
versions them independently.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_appconfig_client, get_config
from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig

logger = logging.getLogger("aurion.admin.feature_flags")

router = APIRouter(prefix="/admin", tags=["admin"])

# Non-session admin action — see admin/config.py for the same sentinel.
_AUDIT_SENTINEL = "system"


# ── Schemas ─────────────────────────────────────────────────────────────────


class FeatureFlagsResponse(BaseModel):
    """Full snapshot of the feature_flags block from live AppConfig.

    Mirrors ``FeatureFlagsConfig`` field-for-field so the portal can
    bind a row per flag without server-side filtering. This mirror is
    load-bearing: ``update_feature_flags`` rebuilds the config from this
    body, so any flag missing here is silently reset to its schema
    default on every save. ``test_response_mirrors_config_field_for_field``
    locks the two field sets together so a newly-added config flag can't
    drift out of this model unnoticed. Snake-case wire matches the rest
    of the admin API; the web portal already speaks snake_case for
    AppConfig responses.
    """

    screen_capture_enabled: bool
    note_versioning_enabled: bool
    session_pause_resume_enabled: bool
    per_session_provider_override: bool
    meta_wearables_enabled: bool
    per_session_visual_evidence_mode_override: bool
    clip_video_interpretation_enabled: bool
    frame_by_frame_video_enabled: bool
    orders_card_enabled: bool
    coding_card_enabled: bool
    patient_summary_card_enabled: bool
    emr_writeback_card_enabled: bool
    media_review_retention_enabled: bool
    measurement_enabled: bool
    video_import_enabled: bool
    # Defaulted (like grounded_synthesis_enabled) so a save from a portal build
    # that predates this field can't 422 — resolves to the safe OFF value.
    multi_clip_import_enabled: bool = False
    note_options_enabled: bool = False
    video_import_drop_zero_face_frames: bool
    specialty_style_in_prompt_enabled: bool
    # Grounded Synthesis Mode (v3.2, #552). Defaulted here (unlike the other,
    # required flags) so a save from a portal build that predates this field
    # can't 422 — and, while the mode is dark, a missing field resolves to the
    # safe OFF value rather than breaking the save. Surfaced so the portal can
    # flip it once GS-9 sign-off lands.
    grounded_synthesis_enabled: bool = False
    prompt_studio_enabled: bool
    prompt_studio_roles: list[str]
    clinician_prompts_note_only: bool
    # Cross-clinician Patient Chart (#604). Defaulted (like
    # grounded_synthesis_enabled) so a save from a portal build that predates
    # this field can't 422 — and while the feature is dark, a missing field
    # resolves to the safe OFF value.
    cross_clinician_chart_enabled: bool = False


class UpdateFeatureFlagsResponse(BaseModel):
    """Returned after a successful POST: the new live state + the
    AppConfig hosted-version number that AWS minted."""

    feature_flags: FeatureFlagsResponse
    appconfig_version: int
    changed_fields: list[str]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _appconfig_ids() -> tuple[str, str, str, str]:
    """Resolve the four AppConfig identifiers from env vars.

    Falls back to the legacy long-form names so a local shell or
    LocalStack init that exported the historical names still binds
    (parallels ``AppConfigClient.__init__``). Raises 500 with a clear
    message if any required ID is missing — there's no safe fallback
    for "push a new hosted config" without knowing where to push.

    Returns ``(application_id, profile_id, environment_id,
    deployment_strategy_id)``.
    """
    app_id = (
        os.getenv("APPCONFIG_APP_ID")
        or os.getenv("APPCONFIG_APPLICATION_ID")
        or ""
    )
    profile_id = os.getenv("APPCONFIG_PROFILE_ID", "")
    env_id = (
        os.getenv("APPCONFIG_ENV_ID")
        or os.getenv("APPCONFIG_ENVIRONMENT_ID")
        or ""
    )
    strategy_id = (
        os.getenv("APPCONFIG_DEPLOYMENT_STRATEGY_ID")
        or os.getenv("APPCONFIG_STRATEGY_ID")
        or ""
    )

    missing = [
        name
        for name, value in (
            ("APPCONFIG_APP_ID", app_id),
            ("APPCONFIG_PROFILE_ID", profile_id),
            ("APPCONFIG_ENV_ID", env_id),
            ("APPCONFIG_DEPLOYMENT_STRATEGY_ID", strategy_id),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=(
                "AppConfig identifiers missing from environment: "
                f"{', '.join(missing)}"
            ),
        )
    return app_id, profile_id, env_id, strategy_id


def _build_response(cfg_feature_flags: FeatureFlagsConfig) -> FeatureFlagsResponse:
    """Build the wire response from a validated ``FeatureFlagsConfig``."""
    return FeatureFlagsResponse(
        screen_capture_enabled=cfg_feature_flags.screen_capture_enabled,
        note_versioning_enabled=cfg_feature_flags.note_versioning_enabled,
        session_pause_resume_enabled=cfg_feature_flags.session_pause_resume_enabled,
        per_session_provider_override=cfg_feature_flags.per_session_provider_override,
        meta_wearables_enabled=cfg_feature_flags.meta_wearables_enabled,
        per_session_visual_evidence_mode_override=(
            cfg_feature_flags.per_session_visual_evidence_mode_override
        ),
        clip_video_interpretation_enabled=(
            cfg_feature_flags.clip_video_interpretation_enabled
        ),
        frame_by_frame_video_enabled=(
            cfg_feature_flags.frame_by_frame_video_enabled
        ),
        orders_card_enabled=cfg_feature_flags.orders_card_enabled,
        coding_card_enabled=cfg_feature_flags.coding_card_enabled,
        patient_summary_card_enabled=cfg_feature_flags.patient_summary_card_enabled,
        emr_writeback_card_enabled=cfg_feature_flags.emr_writeback_card_enabled,
        media_review_retention_enabled=(
            cfg_feature_flags.media_review_retention_enabled
        ),
        measurement_enabled=cfg_feature_flags.measurement_enabled,
        video_import_enabled=cfg_feature_flags.video_import_enabled,
        multi_clip_import_enabled=cfg_feature_flags.multi_clip_import_enabled,
        note_options_enabled=cfg_feature_flags.note_options_enabled,
        video_import_drop_zero_face_frames=(
            cfg_feature_flags.video_import_drop_zero_face_frames
        ),
        specialty_style_in_prompt_enabled=(
            cfg_feature_flags.specialty_style_in_prompt_enabled
        ),
        grounded_synthesis_enabled=cfg_feature_flags.grounded_synthesis_enabled,
        prompt_studio_enabled=cfg_feature_flags.prompt_studio_enabled,
        # Copy the list so the response never aliases the live config's.
        prompt_studio_roles=list(cfg_feature_flags.prompt_studio_roles),
        clinician_prompts_note_only=cfg_feature_flags.clinician_prompts_note_only,
        cross_clinician_chart_enabled=(
            cfg_feature_flags.cross_clinician_chart_enabled
        ),
    )


def _diff_flag_names(
    old: FeatureFlagsConfig, new: FeatureFlagsConfig
) -> list[str]:
    """Return the sorted list of field names that differ between two
    ``FeatureFlagsConfig`` instances. PHI-free by construction —
    booleans only, and we return names not values."""
    old_dump = old.model_dump()
    new_dump = new.model_dump()
    return sorted(k for k in new_dump if old_dump.get(k) != new_dump[k])


def _publish_appconfig_version(
    new_doc: dict[str, Any],
    description: str,
) -> int:
    """Push ``new_doc`` as a new AppConfig hosted-configuration-version
    and start a deployment against the configured strategy.

    Returns the new hosted-version number. Raises 502 if the AWS call
    fails for any reason (network, auth, validator rejection). The
    validator rejection case carries the validator detail in the
    response message so the operator knows what shape AWS expected.
    """
    app_id, profile_id, env_id, strategy_id = _appconfig_ids()
    client = boto3.client(
        "appconfig",
        region_name=os.getenv("AWS_DEFAULT_REGION", "ca-central-1"),
        endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    )

    content = json.dumps(new_doc).encode("utf-8")
    try:
        version_resp = client.create_hosted_configuration_version(
            ApplicationId=app_id,
            ConfigurationProfileId=profile_id,
            Content=content,
            ContentType="application/json",
            Description=description,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("AppConfig create_hosted_configuration_version failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"AppConfig publish failed: {exc}",
        ) from exc

    version_number = int(version_resp["VersionNumber"])

    try:
        client.start_deployment(
            ApplicationId=app_id,
            EnvironmentId=env_id,
            DeploymentStrategyId=strategy_id,
            ConfigurationProfileId=profile_id,
            ConfigurationVersion=str(version_number),
            Description=description,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("AppConfig start_deployment failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"AppConfig deployment failed: {exc}",
        ) from exc

    return version_number


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/feature-flags", response_model=FeatureFlagsResponse)
async def get_feature_flags(
    _: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> FeatureFlagsResponse:
    """Return the current ``feature_flags`` block from live AppConfig.

    ADMIN-only — the portal page that consumes this is itself ADMIN-
    gated. Reads ``get_config()`` which serves the in-memory cached
    AppConfig (refreshed every 30s by the polling client); the returned
    state reflects the most recent successful poll.
    """
    cfg = get_config()
    return _build_response(cfg.feature_flags)


@router.post(
    "/feature-flags", response_model=UpdateFeatureFlagsResponse
)
async def update_feature_flags(
    body: FeatureFlagsResponse,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> UpdateFeatureFlagsResponse:
    """Push a new AppConfig hosted-version with the provided
    ``feature_flags`` block.

    The full ``feature_flags`` block must be supplied (partial updates
    are rejected at the Pydantic boundary — required fields). Every other
    AppConfig section (``providers``, ``model_params``, ``pipeline``,
    ``alerting``, ``model_versions``) is preserved verbatim from the
    current live config, so a feature-flags save never resets them — in
    particular ``model_versions`` carries the AI model-id overrides
    (e.g. the Gemini 3.1 flip, #438).

    On success: emits ``FEATURE_FLAGS_UPDATED`` with the actor UUID,
    sorted list of changed field names, and the new hosted-version
    number. Returns the new live state. ADMIN-only.

    Failure modes:
    - 400 if the proposed config violates ``AppConfigSchema``.
    - 502 if the AWS AppConfig publish / deploy call fails.
    - 500 if the required env vars are missing.
    """
    current = get_config()
    proposed_flags = FeatureFlagsConfig.model_validate(body.model_dump())

    # Compose the full doc, preserving every non-feature-flag section from the
    # live config so a feature-flags save never resets them. model_versions
    # carries the AI model-id overrides (the Gemini flip, #438) and alerting the
    # SLA thresholds; without re-sending them the new hosted version would drop
    # both. exclude_none keeps model_versions valid under the AppConfig schema
    # validator (null model ids aren't strings). `measurement` is intentionally
    # omitted — it isn't in the AppConfig validator's root, so it never belongs
    # in the hosted document.
    proposed_doc = {
        "providers": current.providers.model_dump(mode="json"),
        "model_params": current.model_params.model_dump(mode="json"),
        "pipeline": current.pipeline.model_dump(mode="json"),
        "feature_flags": proposed_flags.model_dump(mode="json"),
        "alerting": current.alerting.model_dump(mode="json"),
        "model_versions": current.model_versions.model_dump(
            mode="json", exclude_none=True
        ),
    }

    # Server-side validation (defense in depth — AWS validator catches
    # this too, but failing locally gives a sharper error message).
    try:
        AppConfigSchema.model_validate(proposed_doc)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid feature_flags update: {exc.errors()}",
        ) from exc

    changed_fields = _diff_flag_names(current.feature_flags, proposed_flags)
    if not changed_fields:
        # No-op writes still return the live state but skip the
        # AppConfig publish + audit — there's nothing to record.
        return UpdateFeatureFlagsResponse(
            feature_flags=_build_response(current.feature_flags),
            appconfig_version=0,
            changed_fields=[],
        )

    description = (
        f"feature_flags update by admin: {', '.join(changed_fields)}"
    )
    version_number = _publish_appconfig_version(proposed_doc, description)

    # Reflect immediately in the serving task so the ADMIN sees the new
    # state without waiting for the 30s poll. Other ECS tasks converge
    # on the next poll.
    appconfig_client = get_appconfig_client()
    appconfig_client._config = AppConfigSchema.model_validate(proposed_doc)  # noqa: SLF001

    await write_audit(
        _AUDIT_SENTINEL,
        AuditEventType.FEATURE_FLAGS_UPDATED,
        changed_by=str(user.user_id),
        changed_fields=changed_fields,
        appconfig_version=version_number,
    )

    return UpdateFeatureFlagsResponse(
        feature_flags=_build_response(proposed_flags),
        appconfig_version=version_number,
        changed_fields=changed_fields,
    )
