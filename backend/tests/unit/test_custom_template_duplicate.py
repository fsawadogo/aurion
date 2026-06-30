"""Unit tests for forking a Library template into My Templates (tpl-central-1 / #575).

`duplicate_into_owner` clones a template the caller owns OR a shared org template
into a NEW owned (is_shared=False) row with a per-owner-unique key + a "(copy)"
name. Mirrors the stubbed-AsyncSession style of test_custom_templates_service.py.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import me as me_mod
from app.core.audit_events import AuditEventType
from app.modules.custom_templates import service as svc


def _tmpl(**over) -> dict:
    base = {
        "key": "k",
        "display_name": "K",
        "version": "1.0",
        "sections": [{"id": "s", "title": "S", "required": True}],
    }
    base.update(over)
    return base


def _src(**over) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),  # owned by someone else (shared case)
        is_shared=True,
        key="k",
        display_name="K",
        content=json.dumps(_tmpl()),
    )
    base.update(over)
    return SimpleNamespace(**base)


# ── service: duplicate_into_owner ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_forks_shared_into_owned(monkeypatch) -> None:
    me = uuid.uuid4()
    src = _src(is_shared=True)
    monkeypatch.setattr(svc, "get_owned_or_shared", AsyncMock(return_value=src))
    monkeypatch.setattr(svc, "_find_by_owner_and_key", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_flush_mapping_unique", AsyncMock())
    db = AsyncMock()
    db.add = MagicMock()

    row = await svc.duplicate_into_owner(src.id, me, db)

    assert row is not None
    assert row.is_shared is False           # a fork is always personal
    assert row.owner_id == me               # owned by the caller, not the source
    assert row.key == "k-copy"
    assert row.display_name == "K (copy)"
    assert json.loads(row.content)["sections"][0]["id"] == "s"  # content copied
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_dedups_key_when_copy_exists(monkeypatch) -> None:
    me = uuid.uuid4()
    src = _src()
    monkeypatch.setattr(svc, "get_owned_or_shared", AsyncMock(return_value=src))
    # "k-copy" taken → "k-copy-2" free → create's own check also free
    monkeypatch.setattr(
        svc, "_find_by_owner_and_key", AsyncMock(side_effect=[MagicMock(), None, None])
    )
    monkeypatch.setattr(svc, "_flush_mapping_unique", AsyncMock())
    db = AsyncMock()
    db.add = MagicMock()

    row = await svc.duplicate_into_owner(src.id, me, db)

    assert row.key == "k-copy-2"


@pytest.mark.asyncio
async def test_duplicate_returns_none_when_source_unresolvable(monkeypatch) -> None:
    """Missing id or a foreign PRIVATE template → get_owned_or_shared None → None."""
    monkeypatch.setattr(svc, "get_owned_or_shared", AsyncMock(return_value=None))
    db = AsyncMock()
    assert await svc.duplicate_into_owner(uuid.uuid4(), uuid.uuid4(), db) is None


# ── route: POST /me/custom-templates/{id}/duplicate ──────────────────────────


@pytest.mark.asyncio
async def test_duplicate_route_forks_and_audits(monkeypatch) -> None:
    forked = SimpleNamespace(id=uuid.uuid4(), key="k-copy")
    monkeypatch.setattr(
        me_mod.custom_templates_service,
        "duplicate_into_owner",
        AsyncMock(return_value=forked),
    )
    monkeypatch.setattr(me_mod, "_to_custom_template_response", MagicMock(return_value="RESP"))
    audit = SimpleNamespace(write_event=AsyncMock())
    monkeypatch.setattr(me_mod, "get_audit_log_service", lambda: audit)
    db = AsyncMock()
    user = SimpleNamespace(user_id=uuid.uuid4())

    result = await me_mod.duplicate_my_custom_template(uuid.uuid4(), user, db)

    assert result == "RESP"
    audit.write_event.assert_awaited_once()
    assert (
        audit.write_event.await_args.kwargs["event_type"]
        == AuditEventType.CUSTOM_TEMPLATE_CREATED
    )
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_duplicate_route_404_when_source_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        me_mod.custom_templates_service,
        "duplicate_into_owner",
        AsyncMock(return_value=None),
    )
    db = AsyncMock()
    user = SimpleNamespace(user_id=uuid.uuid4())

    with pytest.raises(HTTPException) as ei:
        await me_mod.duplicate_my_custom_template(uuid.uuid4(), user, db)
    assert ei.value.status_code == 404


# ── review fixes (#580) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["{not valid json", "null", "[1, 2, 3]", '"a string"'])
async def test_duplicate_rejects_corrupt_source_content(monkeypatch, bad) -> None:
    """A corrupt / non-object source content degrades to a clean CustomTemplateError
    (→ 400), not an unhandled 500 — mirrors template_to_dict's tolerance."""
    src = _src(content=bad)
    monkeypatch.setattr(svc, "get_owned_or_shared", AsyncMock(return_value=src))
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="corrupt"):
        await svc.duplicate_into_owner(src.id, uuid.uuid4(), db)


@pytest.mark.asyncio
async def test_duplicate_forks_over_cap_shared_template(monkeypatch) -> None:
    """A mature shared template that exceeds the create-time section caps stays
    forkable — caps are skipped on copy (same exemption as the update path)."""
    big = _tmpl(sections=[{"id": f"s{i}", "title": "S"} for i in range(60)])
    src = _src(content=json.dumps(big))
    monkeypatch.setattr(svc, "get_owned_or_shared", AsyncMock(return_value=src))
    monkeypatch.setattr(svc, "_find_by_owner_and_key", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_flush_mapping_unique", AsyncMock())
    db = AsyncMock()
    db.add = MagicMock()

    row = await svc.duplicate_into_owner(src.id, uuid.uuid4(), db)

    assert row is not None
    assert len(json.loads(row.content)["sections"]) == 60
