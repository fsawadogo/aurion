"""Global runtime AI-provider override store.

Sits between the per-call override and AppConfig in the provider
registry's precedence chain:

    per-call ``override`` arg  >  DB override store  >  AppConfig value

The registry is synchronous and must stay non-blocking, so it reads
overrides from an in-memory cache via :func:`get_override` — never a DB
call in the hot path. A background poller (:func:`start_override_polling`)
refreshes that cache from the ``provider_overrides`` table every ~10s,
mirroring ``appconfig_client``'s polling pattern. The admin write
endpoints call :func:`set_cached` / :func:`clear_cached` so the task
serving the request reflects the change immediately; other ECS tasks
converge within ~10s on the next poll.

The cache holds only the provider-type → value string mapping. The DB
row carries the audit metadata (set_by, reason, updated_at).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.models import ProviderOverrideModel

logger = logging.getLogger("aurion.config")

_POLL_INTERVAL_SECONDS = 10

# Provider-type → override value string. Empty/absent means "no override".
_cache: dict[str, str] = {}
_lock = asyncio.Lock()

_poll_task: Optional[asyncio.Task] = None


def get_override(provider_type: str) -> Optional[str]:
    """Return the current cached override for ``provider_type``, or None.

    Pure in-memory and synchronous — safe to call from the sync provider
    registry hot path. Never touches the DB.
    """
    return _cache.get(provider_type)


def set_cached(provider_type: str, value: str) -> None:
    """Write an override into the in-memory cache immediately.

    Called by the admin write endpoint after persisting the DB row so the
    serving task reflects the change at once.
    """
    _cache[provider_type] = value


def clear_cached(provider_type: str) -> None:
    """Remove an override from the in-memory cache immediately."""
    _cache.pop(provider_type, None)


async def refresh_overrides() -> None:
    """Reload the full override cache from the ``provider_overrides`` table.

    Replaces the cache atomically under the lock so a concurrent
    :func:`get_override` never sees a half-populated map.
    """
    async with async_session_factory() as session:
        result = await session.execute(select(ProviderOverrideModel))
        rows = result.scalars().all()

    fresh = {row.provider_type: row.provider_value for row in rows}
    async with _lock:
        _cache.clear()
        _cache.update(fresh)


async def _poll_loop() -> None:
    """Refresh the override cache at the configured interval."""
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        try:
            await refresh_overrides()
        except Exception:
            logger.exception("Unexpected error during provider-override poll")


async def start_override_polling() -> None:
    """Start background polling for provider-override changes.

    Disabled when APP_ENV=local (mirrors ``appconfig_client``) so unit
    tests and local runs don't require a live DB poller. The admin write
    endpoints still update the in-memory cache directly, so local manual
    testing of the override path works without the poller.
    """
    global _poll_task

    if os.getenv("APP_ENV", "local") == "local":
        logger.info(
            "Provider-override polling disabled (APP_ENV=local) — "
            "cache updated only via admin writes"
        )
        return

    try:
        await refresh_overrides()
    except Exception:
        logger.warning(
            "Initial provider-override load failed, starting empty", exc_info=True
        )

    _poll_task = asyncio.create_task(_poll_loop())
    logger.info(
        "Provider-override polling started (every %ds)", _POLL_INTERVAL_SECONDS
    )


async def stop_override_polling() -> None:
    """Stop background polling."""
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    _poll_task = None
    logger.info("Provider-override polling stopped")
