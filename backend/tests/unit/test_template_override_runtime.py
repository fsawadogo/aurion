"""Unit tests for the #72 runtime template-override cache.

The pre-existing gap: PUT /admin/templates/{key} persisted to the
``template_overrides`` table but ``get_template()`` kept reading disk —
admin edits were silently inert until a restart. These tests pin the fix:
override-first resolution in ``get_template``, immediate cache updates
from the admin write path, atomic refresh with malformed-row tolerance,
and the local-env poller no-op.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import Template, TemplateSection
from app.modules.note_gen import template_override_cache as cache
from app.modules.note_gen.service import get_template


def _tmpl(key: str, name: str = "Edited") -> Template:
    return Template(
        key=key,
        display_name=name,
        version="2.0",
        sections=[TemplateSection(id="chief_complaint", title="CC", required=True)],
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache._clear_all_for_tests()
    yield
    cache._clear_all_for_tests()


# ── cache primitives ─────────────────────────────────────────────────────────


def test_set_get_clear_roundtrip() -> None:
    assert cache.get_cached_override("general") is None
    t = _tmpl("general")
    cache.set_cached("general", t)
    assert cache.get_cached_override("general") is t
    cache.clear_cached("general")
    assert cache.get_cached_override("general") is None
    # clear is idempotent
    cache.clear_cached("general")


# ── get_template resolution order ────────────────────────────────────────────


def test_get_template_prefers_override_over_disk() -> None:
    disk = get_template("orthopedic_surgery")
    assert disk.display_name != "Edited"  # sanity: disk default

    cache.set_cached("orthopedic_surgery", _tmpl("orthopedic_surgery"))
    assert get_template("orthopedic_surgery").display_name == "Edited"

    cache.clear_cached("orthopedic_surgery")
    assert get_template("orthopedic_surgery").display_name == disk.display_name


def test_get_template_unknown_specialty_falls_back_to_general_override() -> None:
    cache.set_cached("general", _tmpl("general", name="General (edited)"))
    got = get_template("definitely_not_a_specialty")
    assert got.display_name == "General (edited)"


def test_get_template_unknown_specialty_disk_general_when_no_override() -> None:
    got = get_template("definitely_not_a_specialty")
    assert got.key == "general"


def test_override_for_net_new_key_is_servable() -> None:
    """An override row whose key has no disk sibling still resolves via
    get_template — the cache is consulted before the bundled dict."""
    cache.set_cached("sports_medicine", _tmpl("sports_medicine"))
    assert get_template("sports_medicine").key == "sports_medicine"


# ── refresh (poller body) ────────────────────────────────────────────────────


def _row(key: str, content) -> MagicMock:
    row = MagicMock()
    row.template_key = key
    row.content = content
    return row


@pytest.mark.asyncio
async def test_refresh_replaces_cache_and_skips_malformed_rows() -> None:
    good = _tmpl("plastic_surgery").model_dump()
    rows = [_row("plastic_surgery", good), _row("broken", {"not": "a template"})]

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    factory_cm = MagicMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)

    # Pre-seed a stale entry that the refresh must evict (full replace,
    # not merge — a deleted DB row disappears from the cache).
    cache.set_cached("stale_key", _tmpl("stale_key"))

    with patch.object(cache, "async_session_factory", return_value=factory_cm):
        await cache.refresh_template_overrides()

    assert cache.get_cached_override("plastic_surgery") is not None
    assert cache.get_cached_override("broken") is None      # malformed skipped
    assert cache.get_cached_override("stale_key") is None   # evicted


@pytest.mark.asyncio
async def test_polling_noop_when_app_env_local(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    await cache.start_template_override_polling()
    assert cache._poll_task is None
    await cache.stop_template_override_polling()  # safe when never started


# ── admin write path updates the cache immediately ───────────────────────────


@pytest.mark.asyncio
async def test_admin_upsert_sets_cache_immediately() -> None:
    from app.api.v1.admin.templates import upsert_template

    body = _tmpl("musculoskeletal")
    user = MagicMock()
    user.user_id = uuid.uuid4()
    db = AsyncMock()

    with patch(
        "app.api.v1.admin.templates.upsert_override",
        AsyncMock(return_value=body),
    ), patch("app.api.v1.admin.templates.write_audit", AsyncMock()):
        await upsert_template("musculoskeletal", body, user=user, db=db)

    assert cache.get_cached_override("musculoskeletal") is body
    # And the pipeline read path sees it at once.
    assert get_template("musculoskeletal").display_name == "Edited"


@pytest.mark.asyncio
async def test_admin_revert_clears_cache_immediately() -> None:
    from app.api.v1.admin.templates import revert_template

    cache.set_cached("emergency_medicine", _tmpl("emergency_medicine"))
    user = MagicMock()
    user.user_id = uuid.uuid4()
    db = AsyncMock()

    with patch(
        "app.api.v1.admin.templates.delete_override",
        AsyncMock(return_value=True),
    ), patch("app.api.v1.admin.templates.write_audit", AsyncMock()):
        await revert_template("emergency_medicine", user=user, db=db)

    assert cache.get_cached_override("emergency_medicine") is None
    # Pipeline falls back to the disk default.
    assert get_template("emergency_medicine").key == "emergency_medicine"
