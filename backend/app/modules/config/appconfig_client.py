"""AppConfig client — polls AWS AppConfig every 30 seconds.

Falls back to environment variables for local development.
Returns a validated AppConfigSchema instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.modules.config.schema import (
    AppConfigSchema,
)

logger = logging.getLogger("aurion.config")

_POLL_INTERVAL_SECONDS = 30

# Env-var override for the `feature_flags` / `pipeline` sections, LOCAL ONLY.
#
# The .env fallback previously carried only the three provider keys, so every
# flag was pinned to its Pydantic default with no way to change it. Locally
# that made whole features untestable: `video_import_enabled` defaults False,
# so every video-import route 404s, and the admin flag API can't help because
# it publishes an AWS AppConfig hosted version (AppConfig is LocalStack
# Pro-only and docker-compose.override.yml drops it).
#
# Hard-gated on APP_ENV=local. The .env fallback ALSO runs in deployed
# environments whenever AppConfig is unreachable, and there an env var
# silently overriding a flag would be a privacy hazard, not a convenience:
# it could flip a PHI-relevant gate during an outage with no audit trail.
# AppConfig stays the only way to change a flag anywhere else.
_LOCAL_OVERRIDE_SECTIONS = {
    "feature_flags": "AURION_FF_",
    "pipeline": "AURION_PIPELINE_",
}


def _coerce(raw: str) -> object:
    """Parse an env string into bool/int/str for Pydantic to validate."""
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes", "on"):
        return True
    if lowered in ("false", "0", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        return raw


def _local_section_overrides() -> dict[str, dict]:
    """Collect `AURION_FF_* / AURION_PIPELINE_*` overrides. `{}` unless local.

    Field names are matched against the real schema, so a typo is reported
    rather than silently ignored — a flag you think you set but didn't is
    exactly how an "it didn't work" afternoon happens. Values are coerced
    loosely and handed to Pydantic, which remains the validation authority.
    """
    if os.getenv("APP_ENV", "local") != "local":
        return {}
    overrides: dict[str, dict] = {}
    for section, prefix in _LOCAL_OVERRIDE_SECTIONS.items():
        valid = AppConfigSchema.model_fields[section].annotation.model_fields
        values: dict[str, object] = {}
        for key, raw in os.environ.items():
            if not key.startswith(prefix):
                continue
            field = key[len(prefix):].lower()
            if field not in valid:
                logger.warning(
                    "Ignoring %s — %r is not a field of %s", key, field, section
                )
                continue
            values[field] = _coerce(raw)
        if values:
            overrides[section] = values
            logger.info(
                "LOCAL env override for %s: %s", section, sorted(values)
            )
    return overrides


class AppConfigClient:
    """Manages runtime configuration from AWS AppConfig with .env fallback."""

    def __init__(self) -> None:
        self._config: AppConfigSchema = self._load_from_env()
        self._poll_task: Optional[asyncio.Task] = None
        self._app_env = os.getenv("APP_ENV", "local")

        # AWS AppConfig identifiers. Terraform's ECS task definition
        # (infrastructure/ecs.tf:468-469) ships these as the shorter
        # APPCONFIG_APP_ID / APPCONFIG_ENV_ID — read those first and fall
        # back to the long-form names so a local shell or LocalStack init
        # that exported the legacy names still binds.
        self._application_id = (
            os.getenv("APPCONFIG_APP_ID") or os.getenv("APPCONFIG_APPLICATION_ID") or ""
        )
        self._environment_id = (
            os.getenv("APPCONFIG_ENV_ID") or os.getenv("APPCONFIG_ENVIRONMENT_ID") or ""
        )
        self._profile_id = os.getenv("APPCONFIG_PROFILE_ID", "")

        # Build boto3 client with optional endpoint override for LocalStack
        endpoint_url = os.getenv("AWS_ENDPOINT_URL")
        self._client = boto3.client(
            "appconfig",
            region_name=os.getenv("AWS_DEFAULT_REGION", "ca-central-1"),
            endpoint_url=endpoint_url,
        )
        self._appconfigdata_client = boto3.client(
            "appconfigdata",
            region_name=os.getenv("AWS_DEFAULT_REGION", "ca-central-1"),
            endpoint_url=endpoint_url,
        )
        self._next_poll_token: Optional[str] = None

    @property
    def config(self) -> AppConfigSchema:
        return self._config

    async def start_polling(self) -> None:
        """Start background polling for AppConfig updates."""
        if self._app_env == "local" and not self._application_id:
            logger.info("AppConfig polling disabled — using .env fallback (APP_ENV=local)")
            return

        try:
            self._start_config_session()
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("AppConfig polling started (every %ds)", _POLL_INTERVAL_SECONDS)
        except (BotoCoreError, ClientError) as e:
            logger.warning("AppConfig session start failed, using .env fallback: %s", e)

    async def stop_polling(self) -> None:
        """Stop background polling."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("AppConfig polling stopped")

    def _start_config_session(self) -> None:
        """Initialize an AppConfig data session."""
        response = self._appconfigdata_client.start_configuration_session(
            ApplicationIdentifier=self._application_id,
            EnvironmentIdentifier=self._environment_id,
            ConfigurationProfileIdentifier=self._profile_id,
            RequiredMinimumPollIntervalInSeconds=_POLL_INTERVAL_SECONDS,
        )
        self._next_poll_token = response["InitialConfigurationToken"]

    async def _poll_loop(self) -> None:
        """Poll AppConfig at the configured interval."""
        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            try:
                self._fetch_latest()
            except (BotoCoreError, ClientError) as e:
                logger.warning("AppConfig poll failed, keeping current config: %s", e)
            except Exception:
                logger.exception("Unexpected error during AppConfig poll")

    def _fetch_latest(self) -> None:
        """Fetch latest configuration from AppConfig."""
        if not self._next_poll_token:
            return

        response = self._appconfigdata_client.get_latest_configuration(
            ConfigurationToken=self._next_poll_token,
        )
        self._next_poll_token = response["NextPollConfigurationToken"]

        content = response["Configuration"].read()
        if not content:
            # Empty content means no change since last poll
            return

        raw = json.loads(content)
        new_config = AppConfigSchema.model_validate(raw)
        if new_config != self._config:
            logger.info("AppConfig updated: providers=%s", new_config.providers.model_dump())
            self._config = new_config

    def _load_from_env(self) -> AppConfigSchema:
        """Build config from environment variables — local dev fallback."""
        providers_raw: dict = {}
        if v := os.getenv("AURION_PROVIDER_TRANSCRIPTION"):
            providers_raw["transcription"] = v
        if v := os.getenv("AURION_PROVIDER_NOTE_GENERATION"):
            providers_raw["note_generation"] = v
        if v := os.getenv("AURION_PROVIDER_VISION"):
            providers_raw["vision"] = v

        overrides = _local_section_overrides()

        try:
            config = AppConfigSchema(
                providers=providers_raw if providers_raw else {},
                **overrides,
            )
        except Exception:
            logger.warning("Invalid env config, using defaults")
            config = AppConfigSchema()

        logger.info(
            "Config loaded from .env: providers=%s",
            config.providers.model_dump(),
        )
        return config


# ── Module-level singleton ─────────────────────────────────────────────────

_client: Optional[AppConfigClient] = None


def get_appconfig_client() -> AppConfigClient:
    """Return the module-level AppConfigClient singleton."""
    global _client
    if _client is None:
        _client = AppConfigClient()
    return _client


def get_config() -> AppConfigSchema:
    """Convenience: return the current validated config."""
    return get_appconfig_client().config
