"""Unit tests for the Visit Type → Context → Template snapshot (#314, B2).

Three surfaces:

  1. ``resolve_context_template_key`` — the create-time resolver:
     resolution order (template_ref ignored → template_key → specialty
     default), snapshot of a valid built-in key, every "can't resolve"
     fallback path, and stale-pin coercion.
  2. ``create_session`` — persists ``context_id`` + ``template_key``
     verbatim, including the old-client (no-context) path where both are
     None.
  3. ``generate_stage1_note`` — loads ``get_template(template_key or
     specialty)``: the snapshot wins when present, the specialty default
     is used (byte-for-byte) when None.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.session.service import (
    create_session,
    resolve_context_template_key,
)

# Stable fake template catalog so the resolver's validation is isolated
# from whatever templates happen to be on disk.
_AVAILABLE = ["general", "musculoskeletal", "orthopedic_surgery"]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _db_with_profile(profile) -> AsyncMock:
    """An AsyncSession stub whose single execute() resolves to ``profile``
    (or None) via ``scalar_one_or_none``."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute = AsyncMock(return_value=result)
    return db


def _profile(contexts: dict) -> SimpleNamespace:
    return SimpleNamespace(contexts_per_visit_type=json.dumps(contexts))


@pytest.fixture
def available_templates(monkeypatch):
    """Patch ``list_available_templates`` at its definition site — the
    resolver imports it lazily, so the call-time lookup sees the stub."""
    monkeypatch.setattr(
        "app.modules.note_gen.service.list_available_templates",
        lambda: list(_AVAILABLE),
    )
    return _AVAILABLE


# ── resolve_context_template_key — resolution order + snapshot ───────────────


@pytest.mark.asyncio
async def test_resolves_valid_template_key(available_templates):
    """A context pinned to a built-in template snapshots that key."""
    profile = _profile(
        {
            "new_patient": [
                {
                    "id": "ctx_aaaaaaaa",
                    "label": "LL",
                    "template_key": "musculoskeletal",
                    "template_ref": None,
                }
            ]
        }
    )
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_aaaaaaaa"
    )

    assert key == "musculoskeletal"
    assert coerced is False


@pytest.mark.asyncio
async def test_template_ref_is_ignored_when_template_key_present(
    available_templates,
):
    """Resolution order: a non-null ``template_ref`` (phase 2) never
    overrides a valid ``template_key``."""
    profile = _profile(
        {
            "follow_up": [
                {
                    "id": "ctx_bbbbbbbb",
                    "label": "Breast",
                    "template_key": "orthopedic_surgery",
                    "template_ref": "custom_should_be_ignored",
                }
            ]
        }
    )
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "follow_up", "ctx_bbbbbbbb"
    )

    assert key == "orthopedic_surgery"
    assert coerced is False


@pytest.mark.asyncio
async def test_template_ref_alone_does_not_resolve_in_phase1(
    available_templates,
):
    """A context with only a ``template_ref`` (no ``template_key``) falls
    through to the specialty default in phase 1 — custom templates aren't
    wired yet (#318)."""
    profile = _profile(
        {
            "new_patient": [
                {
                    "id": "ctx_cccccccc",
                    "label": "X",
                    "template_key": None,
                    "template_ref": "custom_999",
                }
            ]
        }
    )
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_cccccccc"
    )

    assert key is None
    assert coerced is False


# ── resolve_context_template_key — fallback paths (all → (None, False)) ──────


@pytest.mark.asyncio
async def test_null_template_key_falls_back(available_templates):
    profile = _profile(
        {
            "new_patient": [
                {
                    "id": "ctx_dddddddd",
                    "label": "LL",
                    "template_key": None,
                    "template_ref": None,
                }
            ]
        }
    )
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_dddddddd"
    )

    assert key is None
    assert coerced is False


@pytest.mark.asyncio
async def test_no_context_id_short_circuits_without_db():
    """No ``context_id`` → specialty default, and the profile is never
    even queried (old-client path stays cheap)."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=AssertionError("must not query"))

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", None
    )

    assert key is None
    assert coerced is False
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_no_consultation_type_short_circuits():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=AssertionError("must not query"))

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), None, "ctx_aaaaaaaa"
    )

    assert key is None
    assert coerced is False
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_missing_profile_falls_back():
    db = _db_with_profile(None)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_aaaaaaaa"
    )

    assert key is None
    assert coerced is False


@pytest.mark.asyncio
async def test_visit_type_absent_from_map_falls_back(available_templates):
    profile = _profile({"follow_up": []})
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_aaaaaaaa"
    )

    assert key is None
    assert coerced is False


@pytest.mark.asyncio
async def test_context_id_not_found_falls_back(available_templates):
    profile = _profile(
        {
            "new_patient": [
                {
                    "id": "ctx_aaaaaaaa",
                    "label": "LL",
                    "template_key": "musculoskeletal",
                    "template_ref": None,
                }
            ]
        }
    )
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_zzzzzzzz"
    )

    assert key is None
    assert coerced is False


@pytest.mark.asyncio
async def test_corrupt_contexts_json_falls_back(available_templates):
    profile = SimpleNamespace(contexts_per_visit_type="{not valid json")
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_aaaaaaaa"
    )

    assert key is None
    assert coerced is False


# ── resolve_context_template_key — stale pin coercion ────────────────────────


@pytest.mark.asyncio
async def test_stale_template_key_coerced_to_specialty_default(
    available_templates,
):
    """A pinned key no longer in ``list_available_templates`` is coerced
    to the specialty default (None) and flagged for the count-only audit
    note — never raises."""
    profile = _profile(
        {
            "new_patient": [
                {
                    "id": "ctx_eeeeeeee",
                    "label": "Gone",
                    "template_key": "cardiology_removed",
                    "template_ref": None,
                }
            ]
        }
    )
    db = _db_with_profile(profile)

    key, coerced = await resolve_context_template_key(
        db, uuid.uuid4(), "new_patient", "ctx_eeeeeeee"
    )

    assert key is None
    assert coerced is True


# ── create_session — persistence of the snapshot ─────────────────────────────


def _capture_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_session_persists_context_and_template():
    db = _capture_db()

    session = await create_session(
        db=db,
        clinician_id=uuid.uuid4(),
        specialty="orthopedic_surgery",
        consultation_type="new_patient",
        context_id="ctx_aaaaaaaa",
        template_key="musculoskeletal",
    )

    assert session.context_id == "ctx_aaaaaaaa"
    assert session.template_key == "musculoskeletal"
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_session_old_client_leaves_both_none():
    """Old clients omit context_id; both new columns default to None
    (specialty-default path)."""
    db = _capture_db()

    session = await create_session(
        db=db,
        clinician_id=uuid.uuid4(),
        specialty="general",
    )

    assert session.context_id is None
    assert session.template_key is None


# ── generate_stage1_note — template selection ────────────────────────────────


def _healthy_transcript():
    from app.core.types import Transcript, TranscriptSegment

    return Transcript(
        session_id=str(uuid.uuid4()),
        provider_used="whisper",
        segments=[
            TranscriptSegment(
                id="seg_000",
                start_ms=0,
                end_ms=2000,
                text="Patient describes anterior knee pain for two weeks.",
                is_visual_trigger=False,
                trigger_type=None,
            )
        ],
    )


async def _run_stage1_capturing_template(template_key, specialty):
    """Run generate_stage1_note with the heavy collaborators stubbed and
    return the argument get_template was called with."""
    from app.core.types import Note, NoteSection
    from app.modules.note_gen.service import generate_stage1_note, get_template

    session_id = str(uuid.uuid4())
    # A real Template so downstream completeness scoring still works; the
    # spy just records the key it was asked for.
    real_template = get_template("general")
    get_template_spy = MagicMock(return_value=real_template)

    stub_note = Note(
        session_id=session_id,
        stage=1,
        provider_used="anthropic",
        specialty=specialty,
        sections=[NoteSection(id="chief_complaint", status="not_captured")],
    )
    stub_provider = MagicMock()
    stub_provider.generate_note = AsyncMock(return_value=stub_note)
    fake_registry = MagicMock()
    fake_registry.get_note_provider_with_fallback = MagicMock(
        return_value=stub_provider
    )

    with (
        patch(
            "app.modules.note_gen.service.get_template", get_template_spy
        ),
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
            transcript=_healthy_transcript(),
            specialty=specialty,
            session_id=session_id,
            db=AsyncMock(),
            template_key=template_key,
        )

    return get_template_spy


@pytest.mark.asyncio
async def test_stage1_uses_snapshot_template_key_when_present():
    spy = await _run_stage1_capturing_template(
        template_key="musculoskeletal", specialty="orthopedic_surgery"
    )
    spy.assert_called_once_with("musculoskeletal")


@pytest.mark.asyncio
async def test_stage1_falls_back_to_specialty_when_template_key_none():
    """Byte-for-byte back-compat: None → get_template(specialty)."""
    spy = await _run_stage1_capturing_template(
        template_key=None, specialty="orthopedic_surgery"
    )
    spy.assert_called_once_with("orthopedic_surgery")
