"""Unit tests for the PHI-safe seed rewrite of template authoring.

`upload_template_document` (and the shared `_seed_authoring_session` engine)
must send the FULL source document to the LLM for structure extraction but
persist only a redacted placeholder in `messages_json` — a pasted document may
carry patient specifics, and the message history is stored in the DB. These
tests drive the engine with a capturing stub provider (no network) and assert
the redaction boundary + the generalize instruction.

Sentinel tokens (SENTINEL_*) stand in for any patient-specific content — no
real or realistic PHI lives in the repo.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.template_authoring import service as ta_service

_SENTINEL = "SENTINEL_SOURCE_CONTENT_9F3A"


def _capturing_provider(reply: str):
    """Stub `.generate_text` that records each call's message contents and
    returns `reply`."""
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
    template = {
        "key": "extracted",
        "display_name": "Extracted",
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


@pytest.mark.asyncio
async def test_upload_sends_full_source_to_llm(monkeypatch, stub_db):
    """AC-1: the model must see the full source to extract structure from it."""
    provider, seen = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    await ta_service.upload_template_document(
        uuid.uuid4(), f"Section A. {_SENTINEL}. Section B.", stub_db
    )
    assert any(_SENTINEL in m for m in seen)


@pytest.mark.asyncio
async def test_upload_redacts_source_from_stored_history(monkeypatch, stub_db):
    """AC-2: the persisted history has the placeholder, never the source."""
    provider, _ = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    row, _reply = await ta_service.upload_template_document(
        uuid.uuid4(), f"Section A. {_SENTINEL}. Section B.", stub_db
    )
    assert _SENTINEL not in row.messages_json
    assert "not stored" in row.messages_json


@pytest.mark.asyncio
async def test_upload_includes_generalize_instruction(monkeypatch, stub_db):
    """AC-3: the generalize / strip-PHI instruction reaches the LLM."""
    provider, seen = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    await ta_service.upload_template_document(uuid.uuid4(), "Section A", stub_db)
    assert "GENERALIZE" in " ".join(seen)


@pytest.mark.asyncio
async def test_upload_still_extracts_draft(monkeypatch, stub_db):
    """AC-4: extraction still yields a draft + an active session."""
    provider, _ = _capturing_provider(_draft_reply())
    _patch_registry(monkeypatch, provider)
    row, reply = await ta_service.upload_template_document(
        uuid.uuid4(), "Section A", stub_db
    )
    assert row.status == "active"
    assert reply.draft_template is not None
    assert reply.draft_template.key == "extracted"
    stub_db.add.assert_called_once_with(row)


@pytest.mark.asyncio
async def test_upload_refuses_empty(stub_db):
    with pytest.raises(ValueError, match="empty"):
        await ta_service.upload_template_document(uuid.uuid4(), "   ", stub_db)
