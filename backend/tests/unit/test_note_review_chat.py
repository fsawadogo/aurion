"""Unit tests for the "Fix this note" review-chat service.

Drives the engine with a stubbed provider — no real LLM, no network. The
heart of the suite is `_ground_edit`: the code-level enforcement that an
LLM-emitted note can never smuggle an ungrounded claim into a stored
version, whatever the model echoes.

  * text edits on existing claims keep source provenance and flip
    physician_edited / original_text (parity with manual edit_note).
  * an LLM-mutated source_type/source_id on a surviving claim is restored.
  * unknown claim ids are forcibly re-sourced to physician_edit.
  * invented sections and no-op edits raise GroundingViolation.
  * continue_chat persists conversation turns but never the injected
    note-context message.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.note_review_chat import service as rc_service
from app.modules.note_review_chat.service import GroundingViolation


def _note() -> Note:
    return Note(
        session_id=str(uuid.uuid4()),
        stage=2,
        version=2,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.8,
        sections=[
            NoteSection(
                id="hpi",
                title="HPI",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_001",
                        text="Patient reports right shoulder pain for three weeks.",
                        source_type="transcript",
                        source_id="seg_002",
                        source_quote="shoulder's been hurting three weeks",
                    ),
                    NoteClaim(
                        id="claim_002",
                        text="Pain worsens with overhead activity.",
                        source_type="transcript",
                        source_id="seg_003",
                        source_quote="worse when I reach up",
                    ),
                ],
            ),
            NoteSection(
                id="assessment",
                title="Assessment",
                status="not_captured",
                claims=[],
            ),
        ],
    )


def _emitted(sections) -> Note:
    base = _note().model_dump()
    base["sections"] = sections
    return Note.model_validate(base)


# ── _ground_edit ────────────────────────────────────────────────────────────


def test_ground_edit_text_change_preserves_provenance():
    current = _note()
    emitted = _emitted([
        {
            "id": "hpi",
            "title": "HPI",
            "status": "populated",
            "claims": [
                {
                    "id": "claim_001",
                    "text": "Right shoulder pain, three weeks.",
                    "source_type": "transcript",
                    "source_id": "seg_002",
                    "source_quote": "shoulder's been hurting three weeks",
                },
                current.sections[0].claims[1].model_dump(),
            ],
        },
    ])

    grounded, edited = rc_service._ground_edit(current, emitted)

    assert edited == ["hpi"]
    claim = grounded.get_section("hpi").claims[0]
    assert claim.text == "Right shoulder pain, three weeks."
    assert claim.source_type == "transcript"
    assert claim.source_id == "seg_002"
    assert claim.physician_edited is True
    assert claim.original_text == (
        "Patient reports right shoulder pain for three weeks."
    )
    # Untouched claim rides through verbatim.
    untouched = grounded.get_section("hpi").claims[1]
    assert untouched.physician_edited is False
    assert untouched.text == "Pain worsens with overhead activity."


def test_ground_edit_restores_llm_mutated_source():
    """An LLM that rewrites source_id/source_type on a surviving claim
    does not get to keep it — provenance comes from the current note."""
    current = _note()
    emitted = _emitted([
        {
            "id": "hpi",
            "title": "HPI",
            "status": "populated",
            "claims": [
                {
                    "id": "claim_001",
                    "text": "Patient reports right shoulder pain for three weeks.",
                    "source_type": "visual",
                    "source_id": "frame_9999",
                    "source_quote": "invented",
                },
                {
                    # Real edit on the second claim keeps the turn from
                    # being a pure no-op.
                    "id": "claim_002",
                    "text": "Pain worse overhead.",
                    "source_type": "transcript",
                    "source_id": "seg_003",
                    "source_quote": "worse when I reach up",
                },
            ],
        },
    ])

    grounded, edited = rc_service._ground_edit(current, emitted)

    assert edited == ["hpi"]
    claim = grounded.get_section("hpi").claims[0]
    assert claim.source_type == "transcript"
    assert claim.source_id == "seg_002"
    assert claim.source_quote == "shoulder's been hurting three weeks"
    # Its text didn't change, so it isn't marked edited.
    assert claim.physician_edited is False


def test_ground_edit_source_mutation_alone_is_a_noop():
    """Provenance restoration means a source-only mutation nets to zero —
    and a zero-change edit is rejected (re-prompt, never a new version)."""
    current = _note()
    emitted = _emitted([
        {
            "id": "hpi",
            "title": "HPI",
            "status": "populated",
            "claims": [
                {
                    "id": "claim_001",
                    "text": "Patient reports right shoulder pain for three weeks.",
                    "source_type": "visual",
                    "source_id": "frame_9999",
                    "source_quote": "invented",
                },
                current.sections[0].claims[1].model_dump(),
            ],
        },
    ])
    with pytest.raises(GroundingViolation, match="changed nothing"):
        rc_service._ground_edit(current, emitted)


def test_ground_edit_new_claim_forced_to_physician_edit():
    current = _note()
    emitted = _emitted([
        {
            "id": "assessment",
            "title": "Assessment",
            "status": "populated",
            "claims": [
                {
                    "id": "claim_999",
                    "text": "Patient has a sulfa allergy.",
                    # LLM tries to fabricate a transcript anchor:
                    "source_type": "transcript",
                    "source_id": "seg_777",
                    "source_quote": "not actually said",
                },
            ],
        },
    ])

    grounded, edited = rc_service._ground_edit(current, emitted)

    assert edited == ["assessment"]
    section = grounded.get_section("assessment")
    assert section.status == "populated"
    claim = section.claims[0]
    assert claim.source_type == "physician_edit"
    assert claim.source_id == "pedit_assessment"
    assert claim.source_quote == ""
    assert claim.physician_edited is True
    assert claim.id != "claim_999"  # fresh id, no echo collisions


def test_ground_edit_removal_empties_section():
    current = _note()
    emitted = _emitted([
        {"id": "hpi", "title": "HPI", "status": "populated", "claims": []},
    ])

    grounded, edited = rc_service._ground_edit(current, emitted)

    assert edited == ["hpi"]
    assert grounded.get_section("hpi").claims == []
    assert grounded.get_section("hpi").status == "not_captured"
    # Untouched section carries over from the current note.
    assert grounded.get_section("assessment").status == "not_captured"


def test_ground_edit_rejects_invented_section():
    current = _note()
    emitted = _emitted([
        {
            "id": "plan",
            "title": "Plan",
            "status": "populated",
            "claims": [],
        },
    ])
    with pytest.raises(GroundingViolation, match="plan"):
        rc_service._ground_edit(current, emitted)


def test_ground_edit_rejects_duplicate_claim_ids():
    current = _note()
    dup = current.sections[0].claims[0].model_dump()
    emitted = _emitted([
        {
            "id": "hpi",
            "title": "HPI",
            "status": "populated",
            "claims": [dup, dup],
        },
    ])
    with pytest.raises(GroundingViolation, match="more than once"):
        rc_service._ground_edit(current, emitted)


def test_ground_edit_rejects_noop():
    current = _note()
    emitted = _emitted([s.model_dump() for s in current.sections])
    with pytest.raises(GroundingViolation, match="changed nothing"):
        rc_service._ground_edit(current, emitted)


# ── continue_chat with stub provider ────────────────────────────────────────


@pytest.fixture
def stub_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _stub_provider(responses: list[str]) -> object:
    queue = list(responses)

    class _Stub:
        async def generate_text(self, system, messages):
            if not queue:
                raise AssertionError("provider exhausted — too many LLM calls")
            return queue.pop(0)

    return _Stub()


def _patch_registry(monkeypatch, provider):
    fake_registry = MagicMock()
    fake_registry.get_note_provider = MagicMock(return_value=provider)
    monkeypatch.setattr(rc_service, "get_registry", lambda: fake_registry)


def _chat_row() -> MagicMock:
    row = MagicMock()
    row.messages_json = "[]"
    return row


def _edit_reply(current: Note, new_text: str) -> str:
    doc = current.model_dump()
    doc["sections"][0]["claims"][0]["text"] = new_text
    return (
        "Shortened the HPI.\n```json\n"
        + json.dumps({"action": "edit_note", "note": doc})
        + "\n```"
    )


@pytest.mark.asyncio
async def test_continue_chat_applies_grounded_edit(monkeypatch, stub_db):
    current = _note()
    _patch_registry(
        monkeypatch, _stub_provider([_edit_reply(current, "Shoulder pain ×3w.")])
    )
    row = _chat_row()

    reply = await rc_service.continue_chat(row, current, "shorten the HPI", stub_db)

    assert reply.edited_note is not None
    assert reply.sections_edited == ["hpi"]
    edited_claim = reply.edited_note.get_section("hpi").claims[0]
    assert edited_claim.text == "Shoulder pain ×3w."
    assert edited_claim.physician_edited is True

    # Persisted history = the real conversation only; the injected
    # CURRENT NOTE context message must never land in the row.
    stored = json.loads(row.messages_json)
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[0]["content"] == "shorten the HPI"
    assert "CURRENT NOTE" not in row.messages_json


@pytest.mark.asyncio
async def test_continue_chat_conversational_turn_applies_nothing(
    monkeypatch, stub_db
):
    current = _note()
    _patch_registry(
        monkeypatch,
        _stub_provider(["Which statement should I remove — the first or second?"]),
    )
    row = _chat_row()

    reply = await rc_service.continue_chat(row, current, "remove one", stub_db)

    assert reply.edited_note is None
    assert reply.sections_edited == []


@pytest.mark.asyncio
async def test_continue_chat_grounding_violation_reprompts_then_recovers(
    monkeypatch, stub_db
):
    current = _note()
    bad_doc = current.model_dump()
    bad_doc["sections"].append(
        {"id": "plan", "title": "Plan", "status": "populated", "claims": []}
    )
    bad_reply = (
        "```json\n"
        + json.dumps({"action": "edit_note", "note": bad_doc})
        + "\n```"
    )
    good_reply = _edit_reply(current, "Shoulder pain, 3 weeks.")
    _patch_registry(monkeypatch, _stub_provider([bad_reply, good_reply]))
    row = _chat_row()

    reply = await rc_service.continue_chat(row, current, "tighten it", stub_db)

    assert reply.edited_note is not None
    assert reply.edited_note.get_section("hpi").claims[0].text == (
        "Shoulder pain, 3 weeks."
    )


@pytest.mark.asyncio
async def test_continue_chat_gives_up_after_max_retries(monkeypatch, stub_db):
    current = _note()
    bad_doc = current.model_dump()
    bad_doc["sections"] = [
        {"id": "invented", "title": "X", "status": "populated", "claims": []}
    ]
    bad_reply = (
        "```json\n"
        + json.dumps({"action": "edit_note", "note": bad_doc})
        + "\n```"
    )
    attempts = rc_service._MAX_VALIDATION_RETRIES + 1
    _patch_registry(monkeypatch, _stub_provider([bad_reply] * attempts))
    row = _chat_row()

    reply = await rc_service.continue_chat(row, current, "do the thing", stub_db)

    assert reply.edited_note is None
    assert reply.assistant_message == bad_reply


@pytest.mark.asyncio
async def test_continue_chat_refuses_empty_message(stub_db):
    with pytest.raises(ValueError, match="non-empty"):
        await rc_service.continue_chat(_chat_row(), _note(), "   ", stub_db)


# ── Route flag gating ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_chat_routes_404_while_flag_dark(stub_db):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.api.v1 import notes as notes_api

    cfg = SimpleNamespace(
        feature_flags=SimpleNamespace(note_review_chat_enabled=False)
    )
    with patch.object(notes_api, "get_config", return_value=cfg):
        with pytest.raises(HTTPException) as exc_get:
            await notes_api.get_review_chat(
                session_id=uuid.uuid4(), user=MagicMock(), db=stub_db
            )
        with pytest.raises(HTTPException) as exc_post:
            await notes_api.post_review_chat(
                session_id=uuid.uuid4(),
                body=notes_api.ReviewChatMessageRequest(message="hi"),
                user=MagicMock(),
                db=stub_db,
            )
    assert exc_get.value.status_code == 404
    assert exc_post.value.status_code == 404
