"""loop-2 — starter Library seeding: soap.json content gate + upsert idempotency.

The starter file tests load the REAL ``backend/starter_library/soap.json`` so
a drive-by edit that breaks schema/caps (or drops a required section) fails
here, not at seed time on dev. The upsert tests run against a stubbed session
+ patched service exactly like ``test_custom_templates_service.py`` — the
routine's contract (created / updated / unchanged, service-only writes,
loud failure) is what's pinned, not SQLAlchemy plumbing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.types import Template
from app.modules.custom_templates import service as svc

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_SOAP_PATH = _BACKEND_ROOT / "starter_library" / "soap.json"


def _load_script():
    """Import scripts/seed_library.py as a module (scripts/ isn't a package)."""
    path = _BACKEND_ROOT / "scripts" / "seed_library.py"
    spec = importlib.util.spec_from_file_location("seed_library", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("seed_library", module)
    spec.loader.exec_module(module)
    return module


seed_library = _load_script()


def _soap_payload() -> dict:
    return json.loads(_SOAP_PATH.read_text(encoding="utf-8"))


# ── The starter file itself (AC-1, AC-2) ─────────────────────────────────


def test_soap_json_parses_and_passes_service_caps():
    template = Template.model_validate(_soap_payload())
    # The same gate create_for_owner applies — incl. create-time section caps.
    svc._validate_custom_template_fields(template)
    assert template.key == "soap_universal"
    assert template.detail_level == "standard"


def test_soap_sections_are_the_four_soap_sections_in_order():
    template = Template.model_validate(_soap_payload())
    assert [s.id for s in template.sections] == [
        "subjective",
        "objective",
        "assessment",
        "plan",
    ]
    assert all(s.required for s in template.sections)


def test_soap_only_objective_carries_visual_machinery():
    template = Template.model_validate(_soap_payload())
    by_id = {s.id: s for s in template.sections}
    assert by_id["objective"].visual_trigger_keywords
    assert by_id["objective"].measurement_output_expected is True
    for sid in ("subjective", "assessment", "plan"):
        assert by_id[sid].visual_trigger_keywords == []
        assert by_id[sid].measurement_output_expected is False


def test_soap_guidance_stays_descriptive():
    """The guidance instructs recording, not concluding — the phrases that
    anchor descriptive mode must survive edits."""
    template = Template.model_validate(_soap_payload())
    text = " ".join(s.description.lower() for s in template.sections)
    assert "never infer" in text
    assert template.system_prompt is None


# ── load_starter_templates (loud failure) ────────────────────────────────


def test_load_starter_templates_reads_real_directory():
    payloads = seed_library.load_starter_templates()
    assert any(p.get("key") == "soap_universal" for p in payloads)


def test_load_starter_templates_rejects_broken_json(tmp_path):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(seed_library.SeedError):
        seed_library.load_starter_templates(tmp_path)


def test_load_starter_templates_rejects_empty_directory(tmp_path):
    with pytest.raises(seed_library.SeedError):
        seed_library.load_starter_templates(tmp_path)


# ── upsert contract (AC-3, AC-4, AC-5) ───────────────────────────────────


def _shared_row_for(payload: dict) -> SimpleNamespace:
    template = Template.model_validate(payload)
    return SimpleNamespace(
        id=uuid.uuid4(),
        key=template.key,
        display_name=template.display_name,
        version=template.version,
        content=template.model_dump_json(),
    )


@pytest.mark.asyncio
async def test_upsert_creates_shared_when_absent(monkeypatch):
    created = {}

    async def fake_list_shared(db):
        return []

    async def fake_create(owner_id, payload, db, *, is_shared=False):
        created.update(owner=owner_id, key=payload["key"], is_shared=is_shared)

    monkeypatch.setattr(svc, "list_shared", fake_list_shared)
    monkeypatch.setattr(svc, "create_for_owner", fake_create)
    owner = uuid.uuid4()

    outcome = await seed_library.upsert_shared_template(
        AsyncMock(), owner, _soap_payload()
    )

    assert outcome == "created"
    # AC-5: seeded rows are shared, owned by the resolved admin.
    assert created == {
        "owner": owner,
        "key": "soap_universal",
        "is_shared": True,
    }


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_identical_content(monkeypatch):
    """AC-3: a second run over unchanged files writes nothing."""
    row = _shared_row_for(_soap_payload())

    async def fake_list_shared(db):
        return [row]

    monkeypatch.setattr(svc, "list_shared", fake_list_shared)
    monkeypatch.setattr(
        svc, "create_for_owner", AsyncMock(side_effect=AssertionError("created"))
    )
    monkeypatch.setattr(
        svc, "update_owned", AsyncMock(side_effect=AssertionError("updated"))
    )

    outcome = await seed_library.upsert_shared_template(
        AsyncMock(), uuid.uuid4(), _soap_payload()
    )

    assert outcome == "unchanged"


@pytest.mark.asyncio
async def test_upsert_updates_in_place_on_drift(monkeypatch):
    """AC-4: changed starter content → one service update, no new row."""
    stale = _soap_payload()
    stale["display_name"] = "SOAP — Old name"
    row = _shared_row_for(stale)

    async def fake_list_shared(db):
        return [row]

    update = AsyncMock()
    monkeypatch.setattr(svc, "list_shared", fake_list_shared)
    monkeypatch.setattr(
        svc, "create_for_owner", AsyncMock(side_effect=AssertionError("created"))
    )
    monkeypatch.setattr(svc, "update_owned", update)

    outcome = await seed_library.upsert_shared_template(
        AsyncMock(), uuid.uuid4(), _soap_payload()
    )

    assert outcome == "updated"
    update.assert_awaited_once()
    assert update.await_args.args[0] is row


@pytest.mark.asyncio
async def test_upsert_surfaces_service_rejection_as_seed_error(monkeypatch):
    """AC-5: a validation failure aborts loudly instead of half-seeding."""

    async def fake_list_shared(db):
        return []

    async def fake_create(owner_id, payload, db, *, is_shared=False):
        raise svc.CustomTemplateError("nope")

    monkeypatch.setattr(svc, "list_shared", fake_list_shared)
    monkeypatch.setattr(svc, "create_for_owner", fake_create)

    with pytest.raises(seed_library.SeedError):
        await seed_library.upsert_shared_template(
            AsyncMock(), uuid.uuid4(), _soap_payload()
        )


@pytest.mark.asyncio
async def test_upsert_rejects_schema_invalid_payload():
    with pytest.raises(seed_library.SeedError):
        await seed_library.upsert_shared_template(
            AsyncMock(), uuid.uuid4(), {"key": "x"}
        )


# ── owner resolution (AC-4) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_owner_rejects_unknown_email():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    with pytest.raises(seed_library.SeedError):
        await seed_library.resolve_owner(db, "ghost@example.com")


@pytest.mark.asyncio
async def test_resolve_owner_rejects_non_admin_role():
    user = SimpleNamespace(id=uuid.uuid4(), role="CLINICIAN")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: user)
    with pytest.raises(seed_library.SeedError):
        await seed_library.resolve_owner(db, "doc@example.com")


@pytest.mark.asyncio
async def test_resolve_owner_accepts_admin():
    user = SimpleNamespace(id=uuid.uuid4(), role="ADMIN")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: user)
    assert await seed_library.resolve_owner(db, "admin@example.com") == user.id
