"""Unit tests for custom_templates field caps + per-owner key uniqueness.

The field caps are scoped to the CUSTOM create/update path (not the base
`Template` schema, which trusted built-in specialty templates also use), so
over-long / empty-section input fails as a clean CustomTemplateError (→ 400
at the route) instead of a DataError-500 at flush. These run against a
stubbed AsyncSession — the caps are checked before any DB access, and the
uniqueness probe is the only query.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

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


@pytest.mark.asyncio
async def test_create_rejects_empty_sections():
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="at least one section"):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(sections=[]), db)
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_rejects_overlong_key():
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="key exceeds"):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(key="x" * 51), db)


@pytest.mark.asyncio
async def test_create_rejects_blank_display_name():
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="display name is required"):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(display_name="   "), db)


@pytest.mark.asyncio
async def test_create_rejects_section_without_title():
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="title"):
        await svc.create_for_owner(
            uuid.uuid4(), _tmpl(sections=[{"id": "s", "title": "  "}]), db
        )


@pytest.mark.asyncio
async def test_create_accepts_valid_and_persists():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    no_clash = MagicMock()
    no_clash.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=no_clash)

    row = await svc.create_for_owner(uuid.uuid4(), _tmpl(), db)

    assert row.key == "k"
    assert row.display_name == "K"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_rejects_duplicate_key():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    clash = MagicMock()
    clash.scalars.return_value.first.return_value = MagicMock()
    db.execute = AsyncMock(return_value=clash)

    with pytest.raises(svc.CustomTemplateError, match="already exists"):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(), db)
    db.add.assert_not_called()


# ── create-path cap boundaries (exact-cap passes, cap+1 raises) ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over,match",
    [
        ({"display_name": "x" * 101}, "display name exceeds"),
        ({"version": "x" * 21}, "version exceeds"),
        ({"sections": [{"id": "x" * 51, "title": "T"}]}, "id exceeds"),
        ({"sections": [{"id": "s", "title": "x" * 101}]}, "title exceeds"),
        ({"sections": [{"id": "s", "title": "T", "description": "x" * 501}]}, "description exceeds"),
        ({"sections": [{"id": "s", "title": "T", "visual_trigger_keywords": ["x" * 51]}]}, "keyword exceeds"),
        ({"sections": [{"id": "s", "title": "T", "visual_trigger_keywords": ["k"] * 51}]}, "more than"),
        ({"sections": [{"id": f"s{i}", "title": "T"} for i in range(51)]}, "exceeds 50 sections"),
    ],
)
async def test_create_cap_over_limit_raises(over, match):
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match=match):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(**over), db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "atcap",
    [
        {"display_name": "x" * 100},
        {"version": "x" * 20},
        {"sections": [{"id": "x" * 50, "title": "T"}]},
        {"sections": [{"id": "s", "title": "x" * 100}]},
        {"sections": [{"id": "s", "title": "T", "description": "x" * 500}]},
        {"sections": [{"id": "s", "title": "T", "visual_trigger_keywords": ["x" * 50]}]},
    ],
)
async def test_create_at_cap_passes(atcap):
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    nc = MagicMock()
    nc.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=nc)
    row = await svc.create_for_owner(uuid.uuid4(), _tmpl(**atcap), db)
    assert row is not None
    db.add.assert_called_once()


# ── update path: DB caps enforced, section caps skipped, key-change clash ────


def _row(key: str = "oldkey") -> MagicMock:
    r = MagicMock()
    r.id = uuid.uuid4()
    r.owner_id = uuid.uuid4()
    r.key = key
    return r


@pytest.mark.asyncio
async def test_update_rejects_overlong_key():
    """DB-backed caps (key) ARE enforced on update — would DataError-500 at
    flush otherwise."""
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="key exceeds"):
        await svc.update_owned(_row(), _tmpl(key="x" * 51), db)


@pytest.mark.asyncio
async def test_update_rejects_empty_sections():
    """The >=1-section rule still applies on update (a template can't become
    empty), but never locks out a pre-existing valid row."""
    db = AsyncMock()
    with pytest.raises(svc.CustomTemplateError, match="at least one section"):
        await svc.update_owned(_row(), _tmpl(sections=[]), db)


@pytest.mark.asyncio
async def test_update_skips_section_caps_so_existing_rows_stay_editable():
    """Section length/count caps are NOT enforced on update — a row whose
    sections predate the caps (here a 600-char description) stays saveable.
    The same payload is rejected on CREATE (see the boundary suite)."""
    db = AsyncMock()
    db.flush = AsyncMock()
    row = _row(key="k")  # same key as payload → no clash lookup
    payload = _tmpl(
        key="k",
        sections=[{"id": "s", "title": "T", "description": "x" * 600}],
    )
    result = await svc.update_owned(row, payload, db)
    assert result is row
    assert row.key == "k"
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_update_key_change_rejects_clash():
    db = AsyncMock()
    db.flush = AsyncMock()
    row = _row(key="oldkey")
    clash = MagicMock()
    clash.id = uuid.uuid4()  # different row owns the new key
    res = MagicMock()
    res.scalars.return_value.first.return_value = clash
    db.execute = AsyncMock(return_value=res)
    with pytest.raises(svc.CustomTemplateError, match="already exists"):
        await svc.update_owned(row, _tmpl(key="newkey"), db)


@pytest.mark.asyncio
async def test_update_key_change_no_clash_succeeds():
    db = AsyncMock()
    db.flush = AsyncMock()
    row = _row(key="oldkey")
    res = MagicMock()
    res.scalars.return_value.first.return_value = None  # no clash
    db.execute = AsyncMock(return_value=res)
    result = await svc.update_owned(row, _tmpl(key="newkey"), db)
    assert result is row
    assert row.key == "newkey"


# ── DB unique-constraint mapping (race-proof 409, #3) ────────────────────────


@pytest.mark.asyncio
async def test_create_maps_db_unique_violation_to_clash():
    """If a concurrent insert slips past the in-app check, the DB constraint
    (uq_custom_templates_owner_key) fires at flush — mapped to a friendly
    CustomTemplateError (→ 409), not an unhandled 500."""
    db = AsyncMock()
    db.add = MagicMock()
    nc = MagicMock()
    nc.scalars.return_value.first.return_value = None  # in-app check passes
    db.execute = AsyncMock(return_value=nc)
    db.flush = AsyncMock(
        side_effect=IntegrityError(
            "INSERT",
            {},
            Exception(
                'duplicate key value violates unique constraint '
                '"uq_custom_templates_owner_key"'
            ),
        )
    )
    with pytest.raises(svc.CustomTemplateError, match="already exists"):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(), db)


@pytest.mark.asyncio
async def test_create_reraises_non_unique_integrity_error():
    """A different IntegrityError (e.g. a NOT NULL violation) is NOT swallowed
    as a clash — it propagates."""
    db = AsyncMock()
    db.add = MagicMock()
    nc = MagicMock()
    nc.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=nc)
    db.flush = AsyncMock(
        side_effect=IntegrityError(
            "INSERT", {}, Exception('null value in column "content"')
        )
    )
    with pytest.raises(IntegrityError):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(), db)


@pytest.mark.asyncio
async def test_create_reraises_unrelated_unique_violation():
    """A unique violation on some OTHER constraint isn't mislabeled as a
    per-owner key clash — only uq_custom_templates_owner_key maps to 409."""
    db = AsyncMock()
    db.add = MagicMock()
    nc = MagicMock()
    nc.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=nc)
    db.flush = AsyncMock(
        side_effect=IntegrityError(
            "INSERT",
            {},
            Exception('duplicate key value violates unique constraint "some_other_uq"'),
        )
    )
    with pytest.raises(IntegrityError):
        await svc.create_for_owner(uuid.uuid4(), _tmpl(), db)
