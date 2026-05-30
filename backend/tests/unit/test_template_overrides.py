"""Unit tests for template_overrides service helpers (issue #72).

AsyncMock pattern — mirrors test_alert_service.py / test_auth_active.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import TemplateOverrideModel
from app.core.types import Template, TemplateSection
from app.modules.note_gen import template_overrides as svc


def _t(key: str = "musculoskeletal") -> Template:
    return Template(
        key=key,
        display_name="Musculoskeletal",
        version="1.0",
        sections=[
            TemplateSection(
                id="chief_complaint",
                title="Chief complaint",
                visual_trigger_keywords=["pain", "stiffness"],
            )
        ],
    )


def _row(template: Template) -> TemplateOverrideModel:
    return TemplateOverrideModel(
        template_key=template.key,
        content=template.model_dump(),
        updated_by=None,
        updated_at=datetime.now(timezone.utc),
    )


def _db_returning(rows) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows if isinstance(rows, list) else [rows])
    result.scalars = MagicMock(return_value=scalars)
    result.scalar_one_or_none = MagicMock(
        return_value=rows[0] if isinstance(rows, list) and rows else (rows if not isinstance(rows, list) else None)
    )
    db.execute = AsyncMock(return_value=result)
    return db


class TestListOverrides:
    @pytest.mark.asyncio
    async def test_list_returns_parsed_templates(self) -> None:
        template = _t("musculoskeletal")
        db = _db_returning([_row(template)])
        out = await svc.list_overrides(db)
        assert "musculoskeletal" in out
        assert out["musculoskeletal"].display_name == "Musculoskeletal"

    @pytest.mark.asyncio
    async def test_list_skips_malformed_rows(self, caplog) -> None:
        bad = TemplateOverrideModel(
            template_key="bad",
            content={"missing": "required fields"},
            updated_by=None,
            updated_at=datetime.now(timezone.utc),
        )
        db = _db_returning([bad])
        out = await svc.list_overrides(db)
        assert out == {}


class TestGetOverride:
    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self) -> None:
        db = _db_returning([])
        assert await svc.get_override(db, "musculoskeletal") is None

    @pytest.mark.asyncio
    async def test_returns_parsed_when_present(self) -> None:
        template = _t("plastic_surgery")
        db = _db_returning(_row(template))
        out = await svc.get_override(db, "plastic_surgery")
        assert out is not None
        assert out.key == "plastic_surgery"


class TestUpsertOverride:
    @pytest.mark.asyncio
    async def test_insert_when_missing(self) -> None:
        template = _t("musculoskeletal")
        db = _db_returning([])  # no existing row → insert path
        out = await svc.upsert_override(db, "musculoskeletal", template, updated_by=uuid.uuid4())
        assert out.key == "musculoskeletal"
        assert db.add.call_count == 1
        added = db.add.call_args.args[0]
        assert isinstance(added, TemplateOverrideModel)
        assert added.template_key == "musculoskeletal"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_when_present(self) -> None:
        existing = _row(_t("musculoskeletal"))
        db = _db_returning(existing)
        new_template = _t("musculoskeletal")
        new_template.version = "2.0"
        out = await svc.upsert_override(db, "musculoskeletal", new_template, updated_by=None)
        assert out.version == "2.0"
        assert existing.content["version"] == "2.0"
        # update path doesn't call db.add
        db.add.assert_not_called()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_key_mismatch(self) -> None:
        db = _db_returning([])
        template = _t("musculoskeletal")
        with pytest.raises(ValueError):
            await svc.upsert_override(db, "plastic_surgery", template, updated_by=None)


class TestDeleteOverride:
    @pytest.mark.asyncio
    async def test_returns_false_when_absent(self) -> None:
        db = _db_returning([])
        assert await svc.delete_override(db, "musculoskeletal") is False

    @pytest.mark.asyncio
    async def test_deletes_when_present(self) -> None:
        existing = _row(_t("musculoskeletal"))
        db = _db_returning(existing)
        assert await svc.delete_override(db, "musculoskeletal") is True
        db.delete.assert_awaited_once_with(existing)
        db.flush.assert_awaited_once()
