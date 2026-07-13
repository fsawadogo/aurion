"""Unit tests for note -> template seeding (tpl-from-note).

`create_authoring_from_note` renders a past note's populated sections to text
and delegates to the PHI-safe `_seed_authoring_session` engine (#648). These
tests drive it with a capturing stub provider (no network) and assert: a draft
is extracted, the note content reaches the LLM but is NOT persisted in
`messages_json`, an empty note is rejected, and `_note_to_text` skips sections
with no claims.

Sentinel tokens (SENTINEL_*) stand in for patient-specific note content — no
real or realistic PHI lives in the repo.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.template_authoring import service as ta_service

_SENTINEL = "SENTINEL_NOTE_PHI_7C2"


def _capturing_provider(reply: str):
    seen: list[str] = []

    class _Stub:
        async def generate_text(self, system, messages):
            seen.extend(m.content for m in messages)
            return reply

    return _Stub(), seen


def _patch_registry(monkeypatch, provider):
    fake = MagicMock()
    fake.get_note_provider = MagicMock(return_value=provider)
    monkeypatch.setattr(ta_service, "get_registry", lambda: fake)


def _draft_reply() -> str:
    import json

    template = {
        "key": "from_note",
        "display_name": "From Note",
        "version": "1.0",
        "sections": [{"id": "cc", "title": "Chief Complaint", "required": True}],
    }
    return (
        "```json\n"
        + json.dumps({"action": "draft_template", "template": template})
        + "\n```"
    )


@pytest.fixture
def stub_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _note_with_content() -> Note:
    return Note(
        session_id=str(uuid.uuid4()),
        stage=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="cc",
                title="Chief Complaint",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c1",
                        text=f"Right knee pain for 3 weeks. {_SENTINEL}",
                        source_type="transcript",
                        source_id="seg_1",
                    )
                ],
            ),
            # empty section — must be dropped by _note_to_text
            NoteSection(id="imaging", title="Imaging", status="not_captured", claims=[]),
        ],
    )


@pytest.mark.asyncio
async def test_from_note_extracts_draft(monkeypatch, stub_db):
    """AC-1: a draft lands in an active session."""
    provider, _ = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    row, reply = await ta_service.create_authoring_from_note(
        uuid.uuid4(), _note_with_content(), stub_db
    )
    assert row.status == "active"
    assert reply.draft_template is not None
    assert reply.draft_template.key == "from_note"
    stub_db.add.assert_called_once_with(row)


@pytest.mark.asyncio
async def test_from_note_redacts_note_content(monkeypatch, stub_db):
    """AC-2: note content reaches the LLM but is not persisted (inherits #648)."""
    provider, seen = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    row, _reply = await ta_service.create_authoring_from_note(
        uuid.uuid4(), _note_with_content(), stub_db
    )
    assert _SENTINEL in " ".join(seen)  # reached the LLM
    assert _SENTINEL not in row.messages_json  # not persisted
    assert "not stored" in row.messages_json  # placeholder present


@pytest.mark.asyncio
async def test_from_note_empty_note_raises(monkeypatch, stub_db):
    """AC-3: a note with no populated sections is rejected."""
    provider, _ = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    empty = Note(
        session_id=str(uuid.uuid4()),
        stage=1,
        provider_used="anthropic",
        specialty="general",
        sections=[NoteSection(id="cc", title="CC", status="not_captured", claims=[])],
    )
    with pytest.raises(ValueError, match="no content"):
        await ta_service.create_authoring_from_note(uuid.uuid4(), empty, stub_db)


def test_note_to_text_skips_empty_sections():
    """AC-4: only sections with claims are rendered."""
    text = ta_service._note_to_text(_note_with_content())
    assert "Chief Complaint" in text
    assert "Right knee pain" in text
    assert "Imaging" not in text  # empty / no claims -> skipped
