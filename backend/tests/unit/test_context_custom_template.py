"""Unit tests for binding a CUSTOM template to a context (#318, B3).

Phase 2 of Visit Type → Context → Template: a context can point at a
custom_templates row (``template_ref``) instead of a built-in
``template_key``. Covered here (pure / stubbed — no Postgres):

  1. ``resolve_context_template_key`` — an owned custom ref snapshots a
     ``custom_template_id`` (template_key stays None); a deleted / unowned
     / malformed ref degrades to the specialty default + coercion flag.
     The ownership lookup is SCOPED to the calling clinician (SECURITY).
  2. ``create_session`` — persists ``custom_template_id`` verbatim.
  3. ``_resolve_stage1_template`` — loads + validates custom content when
     an id is present; the None path is byte-for-byte ``get_template``.
  4. ``generate_stage1_note`` — drives the provider with the loaded custom
     template when a ``custom_template_id`` is snapshotted on the session.
  5. ``_diff_contexts`` — count-only custom_templates_attached /
     custom_templates_detached deltas.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.profile import _diff_contexts
from app.core.types import Note, NoteSection, Template, TemplateSection
from app.modules.session.service import (
    create_session,
    resolve_context_template_key,
)

_AVAILABLE = ["general", "musculoskeletal", "orthopedic_surgery"]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _db_with_profile(profile) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute = AsyncMock(return_value=result)
    return db


def _profile(contexts: dict) -> SimpleNamespace:
    return SimpleNamespace(contexts_per_visit_type=json.dumps(contexts))


def _custom_ctx(ref: str, cid: str = "ctx_aaaaaaaa") -> dict:
    return {"id": cid, "label": "LL", "template_key": None, "template_ref": ref}


def _custom_template() -> Template:
    return Template(
        key="custom_ll",
        display_name="Custom Lower Limb",
        version="1.0",
        sections=[
            TemplateSection(id="chief_complaint", title="Chief Complaint"),
        ],
    )


@pytest.fixture
def available_templates(monkeypatch):
    monkeypatch.setattr(
        "app.modules.note_gen.service.list_available_templates",
        lambda: list(_AVAILABLE),
    )
    return _AVAILABLE


# ── resolve_context_template_key — custom ref resolution ──────────────────────


@pytest.mark.asyncio
async def test_owned_custom_ref_snapshots_custom_template_id(
    monkeypatch, available_templates
):
    """An owned, existing custom ref resolves to ``custom_template_id``;
    ``template_key`` stays None and nothing is coerced."""
    custom_id = uuid.uuid4()
    ref = str(custom_id)
    db = _db_with_profile(_profile({"new_patient": [_custom_ctx(ref)]}))

    fake_row = SimpleNamespace(id=custom_id)
    get_owned_mock = AsyncMock(return_value=fake_row)
    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_owned_or_shared", get_owned_mock
    )

    clinician = uuid.uuid4()
    key, cid, coerced = await resolve_context_template_key(
        db, clinician, "new_patient", "ctx_aaaaaaaa"
    )

    assert key is None
    assert cid == custom_id
    assert coerced is False


@pytest.mark.asyncio
async def test_custom_ref_lookup_is_scoped_to_caller(
    monkeypatch, available_templates
):
    """SECURITY: the create-time custom-template lookup is owner-scoped to
    the CALLING clinician — never a global by-id read."""
    custom_id = uuid.uuid4()
    ref = str(custom_id)
    db = _db_with_profile(_profile({"new_patient": [_custom_ctx(ref)]}))

    get_owned_mock = AsyncMock(return_value=SimpleNamespace(id=custom_id))
    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_owned_or_shared", get_owned_mock
    )

    clinician = uuid.uuid4()
    await resolve_context_template_key(
        db, clinician, "new_patient", "ctx_aaaaaaaa"
    )

    # get_owned_or_shared(template_id, owner_id, db) — owner_id MUST be the caller.
    args = get_owned_mock.await_args.args
    assert args[0] == custom_id
    assert args[1] == clinician


@pytest.mark.asyncio
async def test_deleted_or_unowned_custom_ref_coerces_to_default(
    monkeypatch, available_templates
):
    """A valid-UUID ref that no longer resolves to an owned row (deleted
    after profile save, or never owned) degrades to the specialty default
    and flags the count-only coercion audit note."""
    ref = str(uuid.uuid4())
    db = _db_with_profile(_profile({"new_patient": [_custom_ctx(ref)]}))

    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_owned_or_shared",
        AsyncMock(return_value=None),
    )

    key, cid, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_aaaaaaaa"
    )

    assert key is None
    assert cid is None
    assert coerced is True


@pytest.mark.asyncio
async def test_malformed_custom_ref_coerces_without_db_lookup(
    monkeypatch, available_templates
):
    """A non-UUID ref can't reference a custom_templates row — it degrades
    + coerces, and the custom-templates table is never even queried."""
    db = _db_with_profile(_profile({"new_patient": [_custom_ctx("not-a-uuid")]}))

    get_owned_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_owned_or_shared", get_owned_mock
    )

    key, cid, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_aaaaaaaa"
    )

    assert key is None
    assert cid is None
    assert coerced is True
    get_owned_mock.assert_not_awaited()


# ── create_session — persistence of the custom snapshot ───────────────────────


@pytest.mark.asyncio
async def test_create_session_persists_custom_template_id():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    custom_id = uuid.uuid4()

    session = await create_session(
        db=db,
        clinician_id=uuid.uuid4(),
        specialty="orthopedic_surgery",
        consultation_type="new_patient",
        context_id="ctx_aaaaaaaa",
        template_key=None,
        custom_template_id=custom_id,
    )

    assert session.custom_template_id == custom_id
    assert session.template_key is None


@pytest.mark.asyncio
async def test_create_session_defaults_custom_template_id_none():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    session = await create_session(
        db=db, clinician_id=uuid.uuid4(), specialty="general"
    )

    assert session.custom_template_id is None


# ── _resolve_stage1_template — load + validate + defensive fall-through ───────


@pytest.mark.asyncio
async def test_resolve_stage1_template_none_id_uses_get_template():
    """custom_template_id None → byte-for-byte get_template(template_key or
    specialty); the custom-templates table is never touched."""
    from app.modules.note_gen import service as note_service

    spy = MagicMock(return_value=note_service.get_template("general"))
    with patch.object(note_service, "get_template", spy):
        await note_service._resolve_stage1_template(
            template_key="musculoskeletal",
            specialty="orthopedic_surgery",
            custom_template_id=None,
            db=AsyncMock(),
        )
    spy.assert_called_once_with("musculoskeletal")


@pytest.mark.asyncio
async def test_resolve_stage1_template_loads_custom_content(monkeypatch):
    """A valid custom row → its validated Template is returned; the
    built-in get_template is not consulted."""
    from app.modules.note_gen import service as note_service

    custom_id = uuid.uuid4()
    row = SimpleNamespace(content=_custom_template().model_dump_json())
    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(return_value=row),
    )
    spy = MagicMock(side_effect=AssertionError("must not fall back"))
    with patch.object(note_service, "get_template", spy):
        template = await note_service._resolve_stage1_template(
            template_key=None,
            specialty="orthopedic_surgery",
            custom_template_id=custom_id,
            db=AsyncMock(),
        )
    assert template.key == "custom_ll"
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_stage1_template_deleted_row_falls_back(monkeypatch):
    """Row deleted after snapshot → fall back to the specialty default."""
    from app.modules.note_gen import service as note_service

    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(return_value=None),
    )
    fallback = note_service.get_template("general")
    spy = MagicMock(return_value=fallback)
    with patch.object(note_service, "get_template", spy):
        template = await note_service._resolve_stage1_template(
            template_key="musculoskeletal",
            specialty="orthopedic_surgery",
            custom_template_id=uuid.uuid4(),
            db=AsyncMock(),
        )
    assert template is fallback
    spy.assert_called_once_with("musculoskeletal")


@pytest.mark.asyncio
async def test_resolve_stage1_template_invalid_content_falls_back(monkeypatch):
    """Stored content that no longer validates as a Template → fall back
    rather than crash Stage 1."""
    from app.modules.note_gen import service as note_service

    bad_row = SimpleNamespace(content='{"not": "a template"}')
    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(return_value=bad_row),
    )
    fallback = note_service.get_template("general")
    spy = MagicMock(return_value=fallback)
    with patch.object(note_service, "get_template", spy):
        template = await note_service._resolve_stage1_template(
            template_key=None,
            specialty="general",
            custom_template_id=uuid.uuid4(),
            db=AsyncMock(),
        )
    assert template is fallback
    spy.assert_called_once_with("general")


# ── generate_stage1_note — drives the provider with the custom template ───────


@pytest.mark.asyncio
async def test_stage1_generates_against_custom_template(monkeypatch):
    """When the session snapshotted a ``custom_template_id``, Stage 1 loads
    the custom content and hands THAT template to the provider."""
    from app.modules.note_gen.service import generate_stage1_note

    session_id = str(uuid.uuid4())
    custom_id = uuid.uuid4()
    row = SimpleNamespace(content=_custom_template().model_dump_json())
    monkeypatch.setattr(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(return_value=row),
    )

    stub_note = Note(
        session_id=session_id,
        stage=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[NoteSection(id="chief_complaint", status="not_captured")],
    )
    stub_provider = MagicMock()
    stub_provider.generate_note = AsyncMock(return_value=stub_note)
    fake_registry = MagicMock()
    fake_registry.get_note_provider_with_fallback = MagicMock(
        return_value=stub_provider
    )

    from app.core.types import Transcript, TranscriptSegment

    transcript = Transcript(
        session_id=session_id,
        provider_used="whisper",
        segments=[
            TranscriptSegment(
                id="seg_000",
                start_ms=0,
                end_ms=2000,
                text="Patient describes anterior knee pain for two weeks.",
            )
        ],
    )

    with (
        patch(
            "app.modules.note_gen.service.get_registry",
            return_value=fake_registry,
        ),
        patch(
            "app.modules.note_gen.service.assemble_prompt_for_session",
            new_callable=AsyncMock,
            return_value="stub system prompt",
        ),
        patch(
            "app.modules.note_gen.service._load_prior_context_block",
            new_callable=AsyncMock,
            return_value=(None, ""),
        ),
        patch(
            "app.modules.note_gen.service.critique_note",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.note_gen.service._record_provider_usage",
            new_callable=AsyncMock,
        ),
    ):
        await generate_stage1_note(
            transcript=transcript,
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=AsyncMock(),
            custom_template_id=custom_id,
        )

    # The template handed to the provider is the loaded CUSTOM one.
    template_arg = stub_provider.generate_note.await_args.args[1]
    assert template_arg.key == "custom_ll"


# ── _diff_contexts — count-only custom-template deltas ────────────────────────


def _ctx(cid: str, *, tk=None, tr=None) -> dict:
    return {"id": cid, "label": "LL", "template_key": tk, "template_ref": tr}


def test_diff_custom_template_attached():
    before = {"new_patient": [_ctx("ctx_00000001")]}
    after = {"new_patient": [_ctx("ctx_00000001", tr=str(uuid.uuid4()))]}
    deltas = _diff_contexts(before, after)
    assert deltas["custom_templates_attached"] == 1
    assert deltas["custom_templates_detached"] == 0
    assert deltas["templates_attached"] == 0


def test_diff_custom_template_detached():
    before = {"new_patient": [_ctx("ctx_00000001", tr=str(uuid.uuid4()))]}
    after = {"new_patient": []}
    deltas = _diff_contexts(before, after)
    assert deltas["custom_templates_detached"] == 1
    assert deltas["custom_templates_attached"] == 0


def test_diff_custom_template_payload_has_no_ref():
    """The diff carries COUNTS ONLY — a custom ref UUID never leaks."""
    secret_ref = str(uuid.uuid4())
    deltas = _diff_contexts(
        {}, {"new_patient": [_ctx("ctx_00000001", tr=secret_ref)]}
    )
    assert secret_ref not in repr(deltas)
    assert all(isinstance(v, int) for v in deltas.values())
