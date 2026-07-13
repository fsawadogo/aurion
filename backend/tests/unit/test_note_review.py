"""Unit tests for the note-review "fix this note" assistant.

Covers the three layers with a stubbed provider (no network):
  * `_extract_edit_payload` — fenced-JSON edit-block parsing.
  * `_apply_ops` — the grounded apply layer: reword keeps provenance, add is
    cited to a real transcript seg or downgraded to physician_edit (never a
    fabricated citation), remove drops a claim, bad refs are skipped.
  * `assist_note` — orchestration: edits version the note; a conversational
    reply does not.
  * the endpoint flag gate + applied→audit path.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.types import Note, NoteClaim, NoteSection, ProviderError, SessionState
from app.modules.note_review import service as svc
from app.modules.note_review.service import NoteEditOp


def _note() -> Note:
    return Note(
        session_id="s1",
        stage=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="hpi",
                title="HPI",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c1",
                        text="Original HPI text.",
                        source_type="transcript",
                        source_id="seg_001",
                    )
                ],
            ),
            NoteSection(id="allergies", title="Allergies", status="not_captured", claims=[]),
        ],
    )


# ── _extract_edit_payload ───────────────────────────────────────────────────


def test_extract_finds_edit_block():
    text = 'ok\n```json\n{"action":"edit_note","ops":[]}\n```'
    assert svc._extract_edit_payload(text) == {"action": "edit_note", "ops": []}


def test_extract_none_for_conversational():
    assert svc._extract_edit_payload("What did you want to change?") is None


def test_extract_none_for_wrong_action():
    assert svc._extract_edit_payload('```json\n{"action":"other"}\n```') is None


def test_extract_none_for_bad_json():
    assert svc._extract_edit_payload("```json\n{not json}\n```") is None


# ── _apply_ops ──────────────────────────────────────────────────────────────


def test_reword_keeps_provenance():
    op = NoteEditOp(op="reword_claim", claim_id="c1", text="Short HPI.")
    updated, applied = svc._apply_ops(_note(), [op], {})
    assert applied == 1
    claim = updated.get_section("hpi").claims[0]
    assert claim.text == "Short HPI."
    assert claim.physician_edited is True
    assert claim.original_text == "Original HPI text."


def test_reword_unknown_claim_is_skipped():
    op = NoteEditOp(op="reword_claim", claim_id="nope", text="x")
    _updated, applied = svc._apply_ops(_note(), [op], {})
    assert applied == 0


def test_remove_drops_claim():
    op = NoteEditOp(op="remove_claim", claim_id="c1")
    updated, applied = svc._apply_ops(_note(), [op], {})
    assert applied == 1
    assert updated.get_section("hpi").claims == []


def test_add_grounded_claim_is_cited():
    op = NoteEditOp(
        op="add_claim", section_id="allergies", text="Allergic to sulfa.", source_id="seg_035"
    )
    updated, applied = svc._apply_ops(
        _note(), [op], {"seg_035": "I'm allergic to sulfa."}
    )
    assert applied == 1
    sec = updated.get_section("allergies")
    assert sec.status == "populated"
    claim = sec.claims[0]
    assert claim.source_type == "transcript"
    assert claim.source_id == "seg_035"
    assert claim.source_quote == "I'm allergic to sulfa."


def test_add_ungrounded_claim_is_physician_edit_never_fabricated():
    # source_id points at a seg that isn't in the transcript → must NOT be used
    # as a citation; recorded as a physician edit instead.
    op = NoteEditOp(
        op="add_claim", section_id="allergies", text="Prefers morning appointments.",
        source_id="seg_999",
    )
    updated, applied = svc._apply_ops(_note(), [op], {})
    assert applied == 1
    claim = updated.get_section("allergies").claims[0]
    assert claim.source_type == "physician_edit"
    assert claim.source_id == "pedit_allergies"
    assert claim.source_id != "seg_999"  # never a fabricated citation
    assert claim.physician_edited is True


def test_add_to_unknown_section_is_skipped():
    op = NoteEditOp(op="add_claim", section_id="nope", text="x")
    _updated, applied = svc._apply_ops(_note(), [op], {})
    assert applied == 0


# ── assist_note orchestration ───────────────────────────────────────────────


def _patch_provider(monkeypatch, reply: str):
    class _Stub:
        async def generate_text(self, system, messages):
            return reply

    reg = MagicMock()
    reg.get_note_provider = MagicMock(return_value=_Stub())
    monkeypatch.setattr(svc, "get_registry", lambda: reg)
    monkeypatch.setattr(svc, "assemble_prompt_for_session", AsyncMock(return_value="SYS"))
    monkeypatch.setattr(svc, "_load_transcript", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_assist_applies_and_versions(monkeypatch):
    monkeypatch.setattr(svc, "get_latest_note", AsyncMock(return_value=_note()))
    cnv = AsyncMock()
    monkeypatch.setattr(svc, "create_note_version", cnv)
    reply = "```json\n" + json.dumps({
        "action": "edit_note",
        "message": "Shortened the HPI.",
        "ops": [{"op": "reword_claim", "claim_id": "c1", "text": "Short HPI."}],
    }) + "\n```"
    _patch_provider(monkeypatch, reply)

    result = await svc.assist_note("s1", "shorten the hpi", AsyncMock())

    assert result.applied is True
    assert result.assistant_message == "Shortened the HPI."
    assert result.note.get_section("hpi").claims[0].text == "Short HPI."
    cnv.assert_awaited_once()


@pytest.mark.asyncio
async def test_assist_conversational_reply_does_not_version(monkeypatch):
    monkeypatch.setattr(svc, "get_latest_note", AsyncMock(return_value=_note()))
    cnv = AsyncMock()
    monkeypatch.setattr(svc, "create_note_version", cnv)
    _patch_provider(monkeypatch, "Which section did you mean?")

    result = await svc.assist_note("s1", "fix it", AsyncMock())

    assert result.applied is False
    assert result.assistant_message == "Which section did you mean?"
    cnv.assert_not_awaited()


# ── endpoint gate + audit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_403_when_flag_off(monkeypatch):
    from app.api.v1 import notes as notes_module

    cfg = MagicMock()
    cfg.feature_flags.note_review_chat_enabled = False
    monkeypatch.setattr(notes_module, "get_config", lambda: cfg)
    with pytest.raises(HTTPException) as ei:
        await notes_module.assist_note_endpoint(
            session_id=uuid.uuid4(),
            body=notes_module.NoteAssistRequest(message="hi"),
            user=MagicMock(),
            db=AsyncMock(),
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_endpoint_audits_and_commits_when_applied(monkeypatch):
    from app.api.v1 import notes as notes_module

    cfg = MagicMock()
    cfg.feature_flags.note_review_chat_enabled = True
    monkeypatch.setattr(notes_module, "get_config", lambda: cfg)
    session = MagicMock()
    session.state = SessionState.AWAITING_REVIEW
    monkeypatch.setattr(
        notes_module, "get_owned_session_or_404", AsyncMock(return_value=session)
    )
    note = _note()
    note.version = 4
    monkeypatch.setattr(
        notes_module.note_review_service,
        "assist_note",
        AsyncMock(return_value=svc.AssistResult("done", True, note)),
    )
    audit = AsyncMock()
    monkeypatch.setattr(notes_module, "write_audit", audit)
    # Let the real _to_note_response run on the (valid) Note.
    db = AsyncMock()

    resp = await notes_module.assist_note_endpoint(
        session_id=uuid.uuid4(),
        body=notes_module.NoteAssistRequest(message="shorten hpi"),
        user=MagicMock(),
        db=db,
    )

    assert resp.applied is True
    audit.assert_awaited_once()
    assert audit.call_args.args[1] == notes_module.AuditEventType.NOTE_VERSION_CREATED
    db.commit.assert_awaited_once()


# ── multi-op / blank-text / quote-truncation / second-reword ────────────────


def test_apply_multiple_ops_partial():
    ops = [
        NoteEditOp(op="reword_claim", claim_id="c1", text="Short."),
        NoteEditOp(op="reword_claim", claim_id="missing", text="x"),  # skipped
        NoteEditOp(op="add_claim", section_id="allergies", text="Sulfa allergy."),
    ]
    updated, applied = svc._apply_ops(_note(), ops, {})
    assert applied == 2  # reword + add; the missing-claim reword is skipped
    assert updated.get_section("hpi").claims[0].text == "Short."
    assert len(updated.get_section("allergies").claims) == 1


def test_reword_blank_text_is_skipped():
    _updated, applied = svc._apply_ops(
        _note(), [NoteEditOp(op="reword_claim", claim_id="c1", text="   ")], {}
    )
    assert applied == 0


def test_add_blank_text_is_skipped():
    _updated, applied = svc._apply_ops(
        _note(), [NoteEditOp(op="add_claim", section_id="allergies", text="")], {}
    )
    assert applied == 0


def test_add_grounded_quote_truncated_at_cap():
    op = NoteEditOp(op="add_claim", section_id="allergies", text="note", source_id="seg_1")
    updated, _applied = svc._apply_ops(_note(), [op], {"seg_1": "x" * 900})
    assert len(updated.get_section("allergies").claims[0].source_quote) == 500


def test_second_reword_preserves_the_first_original():
    note = _note()
    u1, _ = svc._apply_ops(
        note, [NoteEditOp(op="reword_claim", claim_id="c1", text="Edit 1.")], {}
    )
    u2, _ = svc._apply_ops(
        u1, [NoteEditOp(op="reword_claim", claim_id="c1", text="Edit 2.")], {}
    )
    claim = u2.get_section("hpi").claims[0]
    assert claim.text == "Edit 2."
    assert claim.original_text == "Original HPI text."  # NOT "Edit 1."


# ── retry-exhaustion + PHI-safe re-prompt ───────────────────────────────────


def _capturing_provider(monkeypatch, reply: str):
    """Stub that records the messages sent on each call and always returns
    `reply`. Returns the list of per-call message-content lists."""
    seen: list[list[str]] = []

    class _Stub:
        async def generate_text(self, system, messages):
            seen.append([m.content for m in messages])
            return reply

    reg = MagicMock()
    reg.get_note_provider = MagicMock(return_value=_Stub())
    monkeypatch.setattr(svc, "get_registry", lambda: reg)
    monkeypatch.setattr(svc, "assemble_prompt_for_session", AsyncMock(return_value="SYS"))
    monkeypatch.setattr(svc, "_load_transcript", AsyncMock(return_value=None))
    return seen


@pytest.mark.asyncio
async def test_retry_exhaustion_no_version_and_no_phi_in_reprompt(monkeypatch):
    monkeypatch.setattr(svc, "get_latest_note", AsyncMock(return_value=_note()))
    cnv = AsyncMock()
    monkeypatch.setattr(svc, "create_note_version", cnv)
    # Invalid op enum, with a PHI sentinel in the op payload.
    bad = "```json\n" + json.dumps({
        "action": "edit_note",
        "message": "done",
        "ops": [{"op": "delete_claim", "claim_id": "c1", "text": "SENTINEL_PHI_9Z"}],
    }) + "\n```"
    seen = _capturing_provider(monkeypatch, bad)

    result = await svc.assist_note("s1", "do it", AsyncMock())

    assert result.applied is False
    assert "couldn't apply" in result.assistant_message  # not the model's "done"
    cnv.assert_not_awaited()
    # It retried (>1 call), and the correction turns WE author carry no PHI —
    # only the Pydantic loc+msg summary, never the offending `input`.
    assert len(seen) > 1
    corrections = [msgs[-1] for msgs in seen[1:]]  # the user correction each retry
    assert all("SENTINEL_PHI_9Z" not in c for c in corrections)


@pytest.mark.asyncio
async def test_ops_all_skipped_reports_failure_not_success(monkeypatch):
    monkeypatch.setattr(svc, "get_latest_note", AsyncMock(return_value=_note()))
    cnv = AsyncMock()
    monkeypatch.setattr(svc, "create_note_version", cnv)
    reply = "```json\n" + json.dumps({
        "action": "edit_note",
        "message": "Shortened the HPI.",  # a success claim the edit didn't achieve
        "ops": [{"op": "reword_claim", "claim_id": "ghost", "text": "x"}],
    }) + "\n```"
    _patch_provider(monkeypatch, reply)

    result = await svc.assist_note("s1", "shorten hpi", AsyncMock())

    assert result.applied is False
    assert result.assistant_message != "Shortened the HPI."
    assert "couldn't apply" in result.assistant_message
    cnv.assert_not_awaited()


# ── endpoint error branches + conversational (no audit/commit) ───────────────


async def _run_endpoint(monkeypatch, *, assist_side_effect=None, assist_return=None):
    from app.api.v1 import notes as notes_module

    cfg = MagicMock()
    cfg.feature_flags.note_review_chat_enabled = True
    monkeypatch.setattr(notes_module, "get_config", lambda: cfg)
    session = MagicMock()
    session.state = SessionState.AWAITING_REVIEW
    monkeypatch.setattr(
        notes_module, "get_owned_session_or_404", AsyncMock(return_value=session)
    )
    mock = AsyncMock(side_effect=assist_side_effect, return_value=assist_return)
    monkeypatch.setattr(notes_module.note_review_service, "assist_note", mock)
    audit = AsyncMock()
    monkeypatch.setattr(notes_module, "write_audit", audit)
    db = AsyncMock()
    resp = await notes_module.assist_note_endpoint(
        session_id=uuid.uuid4(),
        body=notes_module.NoteAssistRequest(message="hi"),
        user=MagicMock(),
        db=db,
    )
    return resp, audit, db


@pytest.mark.asyncio
async def test_endpoint_provider_error_maps_to_502(monkeypatch):
    from app.api.v1 import notes as notes_module

    with pytest.raises(HTTPException) as ei:
        await _run_endpoint(
            monkeypatch, assist_side_effect=ProviderError("anthropic", "down")
        )
    assert ei.value.status_code == 502
    _ = notes_module  # keep import used


@pytest.mark.asyncio
async def test_endpoint_value_error_maps_to_404(monkeypatch):
    with pytest.raises(HTTPException) as ei:
        await _run_endpoint(
            monkeypatch, assist_side_effect=ValueError("No note found for session x")
        )
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_conversational_turn_no_audit_no_commit(monkeypatch):
    resp, audit, db = await _run_endpoint(
        monkeypatch,
        assist_return=svc.AssistResult("Which section?", False, _note()),
    )
    assert resp.applied is False
    audit.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_endpoint_blank_message_maps_to_400(monkeypatch):
    from app.api.v1 import notes as notes_module

    cfg = MagicMock()
    cfg.feature_flags.note_review_chat_enabled = True
    monkeypatch.setattr(notes_module, "get_config", lambda: cfg)
    session = MagicMock()
    session.state = SessionState.AWAITING_REVIEW
    monkeypatch.setattr(
        notes_module, "get_owned_session_or_404", AsyncMock(return_value=session)
    )
    with pytest.raises(HTTPException) as ei:
        await notes_module.assist_note_endpoint(
            session_id=uuid.uuid4(),
            body=notes_module.NoteAssistRequest(message="   "),
            user=MagicMock(),
            db=AsyncMock(),
        )
    assert ei.value.status_code == 400
