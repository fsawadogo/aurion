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
    NoteGenerationProviderKey,
    TranscriptionProviderKey,
    VisionProviderKey,
)

logger = logging.getLogger("aurion.config")

_POLL_INTERVAL_SECONDS = 30


class AppConfigClient:
    """Manages runtime configuration from AWS AppConfig with .env fallback."""

    def __init__(self) -> None:
        self._config: AppConfigSchema = self._load_from_env()
        self._poll_task: Optional[asyncio.Task] = None
        self._app_env = os.getenv("APP_ENV", "local")

        # AWS AppConfig identifiers — set by LocalStack init or CDK
        self._application_id = os.getenv("APPCONFIG_APPLICATION_ID", "")
        self._environment_id = os.getenv("APPCONFIG_ENVIRONMENT_ID", "")
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

        try:
            config = AppConfigSchema(
                providers=providers_raw if providers_raw else {},
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
