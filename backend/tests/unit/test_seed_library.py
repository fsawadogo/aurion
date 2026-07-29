"""loop-2 — starter Library seeding: soap.json content gate + upsert idempotency.

The starter file tests load the REAL ``backend/starter_library/soap.json`` so
a drive-by edit that breaks schema/caps (or drops a required section) fails
here, not at seed time on dev. The upsert tests stub the service with
``AsyncMock`` one-liners like ``test_custom_templates_service.py`` — the
routine's contract (created / updated / unchanged / loud failure,
service-only writes) is what's pinned, not SQLAlchemy plumbing.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.types import Template, UserRole
from app.modules.auth import users_repository as users_repo
from app.modules.custom_templates import service as svc

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_SOAP_PATH = _BACKEND_ROOT / "starter_library" / "soap.json"

_SPEC = importlib.util.spec_from_file_location(
    "seed_library", _BACKEND_ROOT / "scripts" / "seed_library.py"
)
seed_library = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed_library)

# Parsed once for the read-only content tests; upsert tests that mutate use
# _soap_payload() for a fresh dict.
SOAP_TEMPLATE = Template.model_validate(
    json.loads(_SOAP_PATH.read_text(encoding="utf-8"))
)


def _soap_payload() -> dict:
    return json.loads(_SOAP_PATH.read_text(encoding="utf-8"))


def _shared_row_for(payload: dict) -> SimpleNamespace:
    template = Template.model_validate(payload)
    return SimpleNamespace(
        key=template.key,
        display_name=template.display_name,
        version=template.version,
        content=template.model_dump_json(),
    )


# ── The starter file itself (AC-1, AC-2) ─────────────────────────────────


def test_soap_json_passes_the_service_create_gate():
    # The same gate create_for_owner applies — incl. create-time section caps.
    svc._validate_custom_template_fields(SOAP_TEMPLATE)
    assert SOAP_TEMPLATE.key == "soap_universal"
    assert SOAP_TEMPLATE.detail_level == "standard"


def test_soap_sections_are_the_four_soap_sections_in_order():
    assert [s.id for s in SOAP_TEMPLATE.sections] == [
        "subjective",
        "objective",
        "assessment",
        "plan",
    ]
    assert all(s.required for s in SOAP_TEMPLATE.sections)


def test_soap_only_objective_carries_visual_machinery():
    by_id = {s.id: s for s in SOAP_TEMPLATE.sections}
    assert by_id["objective"].visual_trigger_keywords
    assert by_id["objective"].measurement_output_expected is True
    for sid in ("subjective", "assessment", "plan"):
        assert by_id[sid].visual_trigger_keywords == []
        assert by_id[sid].measurement_output_expected is False


def test_soap_guidance_stays_descriptive():
    """The guidance instructs recording, not concluding — the phrase that
    anchors descriptive mode must survive edits (deliberate copy canary)."""
    text = " ".join(s.description.lower() for s in SOAP_TEMPLATE.sections)
    assert "never infer" in text
    assert SOAP_TEMPLATE.system_prompt is None


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


async def test_upsert_creates_shared_when_absent(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(svc, "create_for_owner", create)
    owner = uuid.uuid4()
    db = AsyncMock()

    outcome = await seed_library.upsert_shared_template(
        db, owner, _soap_payload(), {}
    )

    assert outcome == "created"
    create.assert_awaited_once()
    args, kwargs = create.await_args
    # AC-5: seeded rows are shared, owned by the resolved admin.
    assert args[0] == owner
    assert args[1]["key"] == "soap_universal"
    assert kwargs == {"is_shared": True}


async def test_upsert_is_idempotent_on_identical_content(monkeypatch):
    """AC-3: a second run over unchanged files writes nothing."""
    row = _shared_row_for(_soap_payload())
    create = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(svc, "create_for_owner", create)
    monkeypatch.setattr(svc, "update_owned", update)

    outcome = await seed_library.upsert_shared_template(
        AsyncMock(), uuid.uuid4(), _soap_payload(), {"soap_universal": [row]}
    )

    assert outcome == "unchanged"
    create.assert_not_awaited()
    update.assert_not_awaited()


async def test_upsert_updates_in_place_on_drift(monkeypatch):
    """AC-4: changed starter content → one service update, no new row."""
    stale = _soap_payload()
    stale["display_name"] = "SOAP — Old name"
    row = _shared_row_for(stale)
    create = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(svc, "create_for_owner", create)
    monkeypatch.setattr(svc, "update_owned", update)

    outcome = await seed_library.upsert_shared_template(
        AsyncMock(), uuid.uuid4(), _soap_payload(), {"soap_universal": [row]}
    )

    assert outcome == "updated"
    create.assert_not_awaited()
    update.assert_awaited_once()
    assert update.await_args.args[0] is row


async def test_upsert_aborts_on_cross_owner_duplicate_key():
    """The DB only enforces (owner_id, key) uniqueness — two shared rows with
    one key must abort loudly, never update 'whichever sorted first'."""
    payload = _soap_payload()
    rows = [_shared_row_for(payload), _shared_row_for(payload)]
    with pytest.raises(seed_library.SeedError):
        await seed_library.upsert_shared_template(
            AsyncMock(), uuid.uuid4(), payload, {"soap_universal": rows}
        )


async def test_upsert_surfaces_service_rejection_as_seed_error(monkeypatch):
    """AC-5: a validation failure aborts loudly instead of half-seeding."""
    monkeypatch.setattr(
        svc,
        "create_for_owner",
        AsyncMock(side_effect=svc.CustomTemplateError("nope")),
    )
    with pytest.raises(seed_library.SeedError):
        await seed_library.upsert_shared_template(
            AsyncMock(), uuid.uuid4(), _soap_payload(), {}
        )


async def test_upsert_rejects_schema_invalid_payload():
    """No monkeypatch: the REAL service gate rejects a payload that isn't a
    Template before touching the (mock) session."""
    with pytest.raises(seed_library.SeedError):
        await seed_library.upsert_shared_template(
            AsyncMock(), uuid.uuid4(), {"key": "x"}, {}
        )


# ── owner resolution (AC-4) ──────────────────────────────────────────────


async def test_resolve_owner_rejects_unknown_email(monkeypatch):
    monkeypatch.setattr(users_repo, "get_by_email", AsyncMock(return_value=None))
    with pytest.raises(seed_library.SeedError):
        await seed_library.resolve_owner(AsyncMock(), "ghost@example.com")


async def test_resolve_owner_rejects_non_admin_role(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.CLINICIAN)
    monkeypatch.setattr(users_repo, "get_by_email", AsyncMock(return_value=user))
    with pytest.raises(seed_library.SeedError):
        await seed_library.resolve_owner(AsyncMock(), "doc@example.com")


async def test_resolve_owner_accepts_admin(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)
    monkeypatch.setattr(users_repo, "get_by_email", AsyncMock(return_value=user))
    assert (
        await seed_library.resolve_owner(AsyncMock(), "admin@example.com")
        == user.id
    )
