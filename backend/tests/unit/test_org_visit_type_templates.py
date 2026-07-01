"""Unit tests for the org-default layer of visit-type template resolution.

Two things under test:
  * the precedence wrapper ``resolve_context_template_key`` — clinician pin/default
    wins, else the org default, else the specialty default — verified by patching
    the two layer helpers (the clinician layer itself is covered by
    test_session_context_template.py);
  * ``_resolve_org_default_template`` — built-in / shared-custom resolution and
    stale-coercion to the specialty default;
  * the admin upsert validation (XOR + built-in / shared-custom checks).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.admin.visit_type_templates import (
    UpsertOrgVisitTypeTemplateRequest,
    upsert_visit_type_template,
)
from app.modules.session import service as svc


def _db() -> AsyncMock:
    return AsyncMock()


def _user() -> SimpleNamespace:
    return SimpleNamespace(user_id=uuid.uuid4(), role=None, email="a@b.com")


# ── Precedence wrapper: resolve_context_template_key ──────────────────────────


@pytest.mark.asyncio
async def test_clinician_pin_wins_over_org_default():
    with (
        patch.object(
            svc,
            "_resolve_clinician_context_template",
            AsyncMock(return_value=("orthopedic_surgery", None, False)),
        ),
        patch.object(svc, "_resolve_org_default_template", AsyncMock()) as org,
    ):
        result = await svc.resolve_context_template_key(
            _db(), uuid.uuid4(), "follow_up", "ctx_1"
        )
    assert result == ("orthopedic_surgery", None, False)
    org.assert_not_awaited()  # clinician resolved → org never consulted


@pytest.mark.asyncio
async def test_org_default_used_when_clinician_has_none():
    org_ct = uuid.uuid4()
    with (
        patch.object(
            svc,
            "_resolve_clinician_context_template",
            AsyncMock(return_value=(None, None, False)),
        ),
        patch.object(
            svc,
            "_resolve_org_default_template",
            AsyncMock(return_value=(None, org_ct)),
        ),
    ):
        tk, ctid, coerced = await svc.resolve_context_template_key(
            _db(), uuid.uuid4(), "follow_up", None
        )
    assert tk is None and ctid == org_ct and coerced is False


@pytest.mark.asyncio
async def test_specialty_default_when_neither():
    with (
        patch.object(
            svc,
            "_resolve_clinician_context_template",
            AsyncMock(return_value=(None, None, False)),
        ),
        patch.object(
            svc,
            "_resolve_org_default_template",
            AsyncMock(return_value=(None, None)),
        ),
    ):
        result = await svc.resolve_context_template_key(
            _db(), uuid.uuid4(), "follow_up", None
        )
    assert result == (None, None, False)


@pytest.mark.asyncio
async def test_coerced_flag_preserved_when_org_fills_in():
    # A stale clinician pin (coerced=True, no template) → the org default fills
    # the template, and the stale flag survives for the count-only audit note.
    with (
        patch.object(
            svc,
            "_resolve_clinician_context_template",
            AsyncMock(return_value=(None, None, True)),
        ),
        patch.object(
            svc,
            "_resolve_org_default_template",
            AsyncMock(return_value=("orthopedic_surgery", None)),
        ),
    ):
        tk, ctid, coerced = await svc.resolve_context_template_key(
            _db(), uuid.uuid4(), "follow_up", "ctx_stale"
        )
    assert tk == "orthopedic_surgery" and coerced is True


@pytest.mark.asyncio
async def test_org_not_consulted_without_consultation_type():
    with (
        patch.object(
            svc,
            "_resolve_clinician_context_template",
            AsyncMock(return_value=(None, None, False)),
        ),
        patch.object(svc, "_resolve_org_default_template", AsyncMock()) as org,
    ):
        result = await svc.resolve_context_template_key(
            _db(), uuid.uuid4(), None, None
        )
    assert result == (None, None, False)
    org.assert_not_awaited()


# ── _resolve_org_default_template ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_org_builtin_resolves_when_available():
    row = SimpleNamespace(
        template_key="orthopedic_surgery", custom_template_id=None
    )
    with (
        patch(
            "app.modules.note_gen.org_visit_type_templates.get_org_default",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.note_gen.service.list_available_templates",
            return_value={"orthopedic_surgery", "general"},
        ),
    ):
        assert await svc._resolve_org_default_template(_db(), "follow_up") == (
            "orthopedic_surgery",
            None,
        )


@pytest.mark.asyncio
async def test_org_builtin_stale_coerces():
    row = SimpleNamespace(
        template_key="renamed_template", custom_template_id=None
    )
    with (
        patch(
            "app.modules.note_gen.org_visit_type_templates.get_org_default",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.note_gen.service.list_available_templates",
            return_value={"orthopedic_surgery"},
        ),
    ):
        assert await svc._resolve_org_default_template(_db(), "follow_up") == (
            None,
            None,
        )


@pytest.mark.asyncio
async def test_org_shared_custom_resolves():
    ct = uuid.uuid4()
    row = SimpleNamespace(template_key=None, custom_template_id=ct)
    with (
        patch(
            "app.modules.note_gen.org_visit_type_templates.get_org_default",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.custom_templates.service.get_shared",
            AsyncMock(return_value=SimpleNamespace(id=ct)),
        ),
    ):
        assert await svc._resolve_org_default_template(_db(), "follow_up") == (
            None,
            ct,
        )


@pytest.mark.asyncio
async def test_org_custom_not_shared_coerces():
    row = SimpleNamespace(template_key=None, custom_template_id=uuid.uuid4())
    with (
        patch(
            "app.modules.note_gen.org_visit_type_templates.get_org_default",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.custom_templates.service.get_shared",
            AsyncMock(return_value=None),
        ),
    ):
        assert await svc._resolve_org_default_template(_db(), "follow_up") == (
            None,
            None,
        )


@pytest.mark.asyncio
async def test_org_no_row_returns_none():
    with patch(
        "app.modules.note_gen.org_visit_type_templates.get_org_default",
        AsyncMock(return_value=None),
    ):
        assert await svc._resolve_org_default_template(_db(), "follow_up") == (
            None,
            None,
        )


# ── Admin upsert validation ───────────────────────────────────────────────────


def test_upsert_request_requires_exactly_one():
    with pytest.raises(ValidationError):
        UpsertOrgVisitTypeTemplateRequest()  # neither
    with pytest.raises(ValidationError):
        UpsertOrgVisitTypeTemplateRequest(
            template_key="orthopedic_surgery", custom_template_id=uuid.uuid4()
        )  # both
    # exactly one each → valid
    UpsertOrgVisitTypeTemplateRequest(template_key="orthopedic_surgery")
    UpsertOrgVisitTypeTemplateRequest(custom_template_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_admin_upsert_rejects_unknown_builtin():
    body = UpsertOrgVisitTypeTemplateRequest(template_key="not_a_template")
    with patch(
        "app.api.v1.admin.visit_type_templates.list_available_templates",
        return_value={"orthopedic_surgery"},
    ):
        with pytest.raises(HTTPException) as exc:
            await upsert_visit_type_template("follow_up", body, _user(), _db())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_admin_upsert_rejects_non_shared_custom():
    body = UpsertOrgVisitTypeTemplateRequest(custom_template_id=uuid.uuid4())
    with patch(
        "app.api.v1.admin.visit_type_templates.get_shared",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc:
            await upsert_visit_type_template("follow_up", body, _user(), _db())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_admin_upsert_builtin_ok():
    body = UpsertOrgVisitTypeTemplateRequest(template_key="orthopedic_surgery")
    saved = SimpleNamespace(
        visit_type="follow_up",
        template_key="orthopedic_surgery",
        custom_template_id=None,
        updated_at=None,
    )
    with (
        patch(
            "app.api.v1.admin.visit_type_templates.list_available_templates",
            return_value={"orthopedic_surgery"},
        ),
        patch(
            "app.api.v1.admin.visit_type_templates.upsert_org_default",
            AsyncMock(return_value=saved),
        ),
        patch(
            "app.api.v1.admin.visit_type_templates.write_audit", AsyncMock()
        ),
    ):
        resp = await upsert_visit_type_template(
            "follow_up", body, _user(), _db()
        )
    assert resp.visit_type == "follow_up"
    assert resp.template_key == "orthopedic_surgery"
