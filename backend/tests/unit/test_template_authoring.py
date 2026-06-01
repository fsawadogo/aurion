"""Unit tests for the conversational template authoring service.

Drives the engine with a stubbed provider — no real LLM, no network —
so the validate-then-retry loop, the fenced-JSON extraction, and the
history-truncation invariants are exercised without flake.

Targets the engine surface:

  * `_extract_draft` — fenced JSON block parsing (presence, action tag,
    JSON validity).
  * `_truncate_history` — keeps the bootstrap message + most-recent
    turns when over the cap.
  * `continue_authoring` — happy path stores draft + history; bad
    draft triggers retry; max-retries surfaces reply without draft.
  * `upload_template_document` — seeds an active session with a draft
    when the LLM extracts cleanly.
  * `finalize_authoring` — promotes draft to a custom_templates row,
    flips status to completed.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.providers.base import ChatMessage
from app.modules.template_authoring import service as ta_service


# ── _extract_draft unit ────────────────────────────────────────────────────


def test_extract_draft_finds_fenced_block():
    text = (
        "Sure, here's the draft:\n\n"
        "```json\n"
        '{"action":"draft_template","template":{"key":"x","display_name":"X"}}\n'
        "```\n"
        "Let me know if you want to refine."
    )
    out = ta_service._extract_draft(text)
    assert out == {"key": "x", "display_name": "X"}


def test_extract_draft_returns_none_without_fence():
    assert ta_service._extract_draft("Just plain text, no JSON.") is None


def test_extract_draft_returns_none_for_wrong_action():
    text = '```json\n{"action":"something_else","template":{"key":"x"}}\n```'
    assert ta_service._extract_draft(text) is None


def test_extract_draft_returns_none_for_invalid_json():
    text = "```json\n{not valid json}\n```"
    assert ta_service._extract_draft(text) is None


def test_extract_draft_returns_none_when_template_not_dict():
    text = '```json\n{"action":"draft_template","template":"oops"}\n```'
    assert ta_service._extract_draft(text) is None


# ── _truncate_history unit ─────────────────────────────────────────────────


def test_truncate_keeps_bootstrap_and_tail():
    """When over the cap, head[0] + last N-1 messages are preserved."""
    cap = ta_service._MAX_MESSAGES
    history = [
        ChatMessage(role="assistant", content="bootstrap")
    ] + [
        ChatMessage(role="user", content=f"u{i}") for i in range(cap + 5)
    ]
    out = ta_service._truncate_history(history)
    assert len(out) == cap
    assert out[0].content == "bootstrap"
    # Last item is the most-recent input.
    assert out[-1].content.startswith("u")


def test_truncate_passes_through_when_under_cap():
    history = [ChatMessage(role="user", content="hi")]
    out = ta_service._truncate_history(history)
    assert out == history


# ── continue_authoring with stub provider ──────────────────────────────────


@pytest.fixture
def stub_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _stub_provider(responses: list[str]) -> object:
    """Build an object with `.generate_text(...)` returning queued replies.
    Exhausting the queue raises so a runaway retry loop fails loudly."""
    queue = list(responses)

    class _Stub:
        async def generate_text(self, system, messages):
            if not queue:
                raise AssertionError("provider exhausted — too many LLM calls")
            return queue.pop(0)

    return _Stub()


def _patch_registry(monkeypatch, provider):
    """Point `get_registry().get_note_provider()` at our stub provider."""
    fake_registry = MagicMock()
    fake_registry.get_note_provider = MagicMock(return_value=provider)
    monkeypatch.setattr(ta_service, "get_registry", lambda: fake_registry)


@pytest.mark.asyncio
async def test_continue_authoring_happy_path_stores_draft(
    monkeypatch, stub_db
):
    """Provider returns a clean fenced draft; the row gets the draft +
    extended history, and the caller sees both."""
    template_json = {
        "key": "ortho_postop",
        "display_name": "Orthopedic Post-Op",
        "version": "1.0",
        "sections": [
            {
                "id": "rom",
                "title": "Range of Motion",
                "required": True,
                "visual_trigger_keywords": [],
                "description": "",
            }
        ],
    }
    assistant_reply = (
        "Here's a draft:\n```json\n"
        + json.dumps({"action": "draft_template", "template": template_json})
        + "\n```"
    )
    _patch_registry(monkeypatch, _stub_provider([assistant_reply]))

    row = MagicMock()
    row.status = "active"
    row.messages_json = json.dumps([
        {"role": "assistant", "content": "Hi!"},
    ])

    reply = await ta_service.continue_authoring(row, "Build me an ortho template", stub_db)

    assert reply.draft_template is not None
    assert reply.draft_template.key == "ortho_postop"
    assert "Here's a draft" in reply.assistant_message

    # Row was mutated with the new draft + extended history.
    stored = json.loads(row.draft_template_json)
    assert stored["key"] == "ortho_postop"
    stored_messages = json.loads(row.messages_json)
    assert stored_messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_continue_authoring_validation_retry_recovers(
    monkeypatch, stub_db
):
    """First reply emits an invalid draft; second reply (after the
    correction re-prompt) emits a valid one. The caller sees the
    second reply + the valid draft."""
    invalid_reply = (
        '```json\n{"action":"draft_template","template":{"display_name":"missing_key"}}\n```'
    )
    valid_template = {
        "key": "musculo",
        "display_name": "Musculoskeletal",
        "version": "1.0",
        "sections": [],
    }
    valid_reply = (
        "Got it — corrected:\n```json\n"
        + json.dumps({"action": "draft_template", "template": valid_template})
        + "\n```"
    )
    _patch_registry(monkeypatch, _stub_provider([invalid_reply, valid_reply]))

    row = MagicMock()
    row.status = "active"
    row.messages_json = json.dumps([])

    reply = await ta_service.continue_authoring(row, "Build it", stub_db)

    assert reply.draft_template is not None
    assert reply.draft_template.key == "musculo"
    assert "corrected" in reply.assistant_message


@pytest.mark.asyncio
async def test_continue_authoring_max_retries_surfaces_reply_without_draft(
    monkeypatch, stub_db
):
    """All replies emit invalid drafts; after _MAX_VALIDATION_RETRIES+1
    attempts we surface the last assistant text with draft=None rather
    than 500'ing the request."""
    invalid_reply = (
        '```json\n{"action":"draft_template","template":{"oops":"no key"}}\n```'
    )
    # _MAX_VALIDATION_RETRIES + 1 attempts total
    attempts = ta_service._MAX_VALIDATION_RETRIES + 1
    _patch_registry(monkeypatch, _stub_provider([invalid_reply] * attempts))

    row = MagicMock()
    row.status = "active"
    row.messages_json = json.dumps([])

    reply = await ta_service.continue_authoring(row, "Build it", stub_db)
    assert reply.draft_template is None
    assert reply.assistant_message == invalid_reply


@pytest.mark.asyncio
async def test_continue_authoring_refuses_non_active_session(stub_db):
    row = MagicMock()
    row.status = "completed"
    row.messages_json = "[]"

    with pytest.raises(ValueError, match="Cannot continue"):
        await ta_service.continue_authoring(row, "more", stub_db)


@pytest.mark.asyncio
async def test_continue_authoring_refuses_empty_message(stub_db):
    row = MagicMock()
    row.status = "active"
    row.messages_json = "[]"

    with pytest.raises(ValueError, match="non-empty"):
        await ta_service.continue_authoring(row, "   ", stub_db)


# ── upload_template_document with stub provider ────────────────────────────


@pytest.mark.asyncio
async def test_upload_template_document_seeds_active_session_with_draft(
    monkeypatch, stub_db
):
    template_json = {
        "key": "uploaded",
        "display_name": "Uploaded Template",
        "version": "1.0",
        "sections": [],
    }
    assistant_reply = (
        "```json\n"
        + json.dumps({"action": "draft_template", "template": template_json})
        + "\n```"
    )
    _patch_registry(monkeypatch, _stub_provider([assistant_reply]))

    row, reply = await ta_service.upload_template_document(
        uuid.uuid4(), "Section A\nSection B\nSection C", stub_db
    )

    assert row.status == "active"
    assert reply.draft_template is not None
    assert reply.draft_template.key == "uploaded"

    # New row was added to the db session
    stub_db.add.assert_called_once_with(row)


@pytest.mark.asyncio
async def test_upload_template_document_refuses_empty(stub_db):
    with pytest.raises(ValueError, match="empty"):
        await ta_service.upload_template_document(uuid.uuid4(), "   ", stub_db)


# ── finalize_authoring ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_promotes_draft_and_marks_completed(stub_db):
    template_json = {
        "key": "final",
        "display_name": "Final",
        "version": "1.0",
        "sections": [],
    }
    row = MagicMock()
    row.id = uuid.uuid4()
    row.owner_id = uuid.uuid4()
    row.status = "active"
    row.draft_template_json = json.dumps(template_json)

    custom = await ta_service.finalize_authoring(row, stub_db)

    assert custom.key == "final"
    assert custom.display_name == "Final"
    assert custom.owner_id == row.owner_id
    assert row.status == "completed"
    stub_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_refuses_when_no_draft(stub_db):
    row = MagicMock()
    row.status = "active"
    row.draft_template_json = None

    with pytest.raises(ValueError, match="No draft"):
        await ta_service.finalize_authoring(row, stub_db)


@pytest.mark.asyncio
async def test_finalize_refuses_when_already_completed(stub_db):
    row = MagicMock()
    row.status = "completed"
    row.draft_template_json = '{"key":"x"}'

    with pytest.raises(ValueError, match="Cannot finalize"):
        await ta_service.finalize_authoring(row, stub_db)
