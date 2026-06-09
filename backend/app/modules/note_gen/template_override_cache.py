"""Runtime template-override cache (issue #72 — the follow-up the
override store promised).

Before this module, an override written via PUT /admin/templates/{key}
landed in the ``template_overrides`` table but the running pipeline kept
reading the disk-bundled JSON — the CRUD was inert until a restart. This
closes that gap, mirroring ``app/modules/config/provider_overrides.py``
exactly:

- ``get_cached_override`` is pure in-memory and synchronous, safe for the
  sync ``get_template()`` hot path — never a DB call.
- The admin write endpoints call :func:`set_cached` / :func:`clear_cached`
  after persisting, so the task serving the request reflects the change
  immediately.
- A background poller (:func:`start_template_override_polling`, every
  ~10s, disabled when APP_ENV=local) converges the rest of the ECS fleet.

Layering: this module imports only core (models/database/types) — NOT
``note_gen.service`` — so ``service.get_template`` can import it without a
cycle (``template_overrides.py`` already imports service the other way).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.models import TemplateOverrideModel
from app.core.types import Template

logger = logging.getLogger("aurion.note_gen.template_override_cache")

_POLL_INTERVAL_SECONDS = 10

# template_key → validated Template. Absent key means "no override; use
# the disk-bundled default".
_cache: dict[str, Template] = {}
_lock = asyncio.Lock()

_poll_task: Optional[asyncio.Task] = None


def get_cached_override(template_key: str) -> Optional[Template]:
    """Return the cached override for ``template_key``, or None.

    Pure in-memory and synchronous — safe to call from the sync
    ``get_template()`` pipeline hot path.
    """
    return _cache.get(template_key)


def set_cached(template_key: str, template: Template) -> None:
    """Write an override into the in-memory cache immediately. Called by
    the admin PUT endpoint after persisting the DB row."""
    _cache[template_key] = template


def clear_cached(template_key: str) -> None:
    """Remove an override from the in-memory cache immediately. Called by
    the admin DELETE (revert) endpoint."""
    _cache.pop(template_key, None)


def _clear_all_for_tests() -> None:
    """Test hook — reset the cache between cases."""
    _cache.clear()


async def refresh_template_overrides() -> None:
    """Reload the full override cache from the ``template_overrides``
    table, replacing it atomically under the lock. Malformed rows are
    skipped with a warning (a bad row must never evict the good ones or
    crash the poller)."""
    async with async_session_factory() as session:
        result = await session.execute(select(TemplateOverrideModel))
        rows = result.scalars().all()

    fresh: dict[str, Template] = {}
    for row in rows:
        try:
            fresh[row.template_key] = Template(**row.content)
        except Exception as exc:  # noqa: BLE001 — best-effort, keep polling
            logger.warning(
                "skipping malformed template override row template_key=%s: %s",
                row.template_key,
                exc,
            )

    async with _lock:
        _cache.clear()
        _cache.update(fresh)


async def _poll_loop() -> None:
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        try:
            await refresh_template_overrides()
        except Exception:
            logger.exception("Unexpected error during template-override poll")


async def start_template_override_polling() -> None:
    """Start background polling for template-override changes.

    Disabled when APP_ENV=local (mirrors ``provider_overrides``) so unit
    tests and local runs don't require a live DB poller; the admin writes
    still update the in-memory cache directly.
    """
    global _poll_task

    if os.getenv("APP_ENV", "local") == "local":
        logger.info(
            "Template-override polling disabled (APP_ENV=local) — "
            "cache updated only via admin writes"
        )
        return

    try:
        await refresh_template_overrides()
    except Exception:
        logger.warning(
            "Initial template-override load failed, starting empty",
            exc_info=True,
        )

    _poll_task = asyncio.create_task(_poll_loop())
    logger.info(
        "Template-override polling started (every %ds)", _POLL_INTERVAL_SECONDS
    )


async def stop_template_override_polling() -> None:
    """Stop background polling."""
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    _poll_task = None
    logger.info("Template-override polling stopped")
