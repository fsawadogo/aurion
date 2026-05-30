"""Unit tests for the Stage 1 self-critique pass (Tier 1 / item D)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import (
    Note,
    NoteClaim,
    NoteSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.note_gen import critique as critique_mod
from app.modules.note_gen.critique import (
    _apply_actions,
    _build_critique_prompt,
    critique_note,
)


def _transcript() -> Transcript:
    return Transcript(
        session_id="s",
        provider_used="whisper",
        segments=[
            TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hello"),
            TranscriptSegment(id="seg_002", start_ms=1000, end_ms=2000, text="world"),
        ],
    )


def _note() -> Note:
    return Note(
        session_id="s",
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="general",
        sections=[
            NoteSection(
                id="chief_complaint",
                title="CC",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_001",
                        text="Physician noted shoulder pain",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="shoulder pain for 2 weeks",
                    ),
                    NoteClaim(
                        id="claim_bad",
                        text="Physician noted X",
                        source_type="transcript",
                        source_id="seg_999",  # ← not in transcript
                        source_quote="",
                    ),
                ],
            ),
            NoteSection(
                id="plan",
                title="Plan",
                status="populated",
                claims=[],  # ← populated but empty
            ),
        ],
        completeness_score=0.5,
    )


def _stub_post(json_payload: dict) -> AsyncMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_payload)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestApplyActions:
    def test_drop_claim_removes_it(self) -> None:
        note = _note()
        applied = _apply_actions(note, [{
            "action": "drop_claim",
            "section_id": "chief_complaint",
            "claim_id": "claim_bad",
            "reason": "source_id not in transcript",
        }])
        assert applied == 1
        ids = [c.id for c in note.sections[0].claims]
        assert "claim_001" in ids
        assert "claim_bad" not in ids

    def test_set_section_status_flips(self) -> None:
        note = _note()
        applied = _apply_actions(note, [{
            "action": "set_section_status",
            "section_id": "plan",
            "new_status": "not_captured",
            "reason": "no claims",
        }])
        assert applied == 1
        plan = next(s for s in note.sections if s.id == "plan")
        assert plan.status == "not_captured"

    def test_unknown_section_ignored(self) -> None:
        note = _note()
        applied = _apply_actions(note, [{
            "action": "drop_claim",
            "section_id": "ghost",
            "claim_id": "anything",
            "reason": "doesn't exist",
        }])
        assert applied == 0

    def test_invalid_status_ignored(self) -> None:
        note = _note()
        applied = _apply_actions(note, [{
            "action": "set_section_status",
            "section_id": "plan",
            "new_status": "garbage",
            "reason": "should be rejected",
        }])
        assert applied == 0
        plan = next(s for s in note.sections if s.id == "plan")
        assert plan.status == "populated"  # unchanged


class TestBuildPrompt:
    def test_includes_valid_segment_ids_for_audit(self) -> None:
        prompt = _build_critique_prompt(_note(), _transcript())
        assert "seg_001" in prompt
        assert "seg_002" in prompt
        # The bad claim's source_id is FLAGGED as invalid in the prompt
        assert "valid=False" in prompt
        # Empty section is rendered
        assert "(no claims)" in prompt


class TestCritiqueNoOpPaths:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_note_unchanged(self, monkeypatch) -> None:
        monkeypatch.setattr(critique_mod, "_ANTHROPIC_API_KEY", "")
        note = _note()
        out = await critique_note(note, _transcript())
        assert out is note
        assert len(out.sections[0].claims) == 2  # nothing dropped

    @pytest.mark.asyncio
    async def test_empty_note_returns_immediately(self, monkeypatch) -> None:
        monkeypatch.setattr(critique_mod, "_ANTHROPIC_API_KEY", "key")
        empty = Note(
            session_id="s", stage=1, version=1, provider_used="x",
            specialty="general", sections=[], completeness_score=0.0,
        )
        out = await critique_note(empty, _transcript())
        assert out.sections == []

    @pytest.mark.asyncio
    async def test_http_error_preserves_note(self, monkeypatch) -> None:
        monkeypatch.setattr(critique_mod, "_ANTHROPIC_API_KEY", "key")
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("boom"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch("httpx.AsyncClient", return_value=client):
            note = _note()
            await critique_note(note, _transcript())
        assert len(note.sections[0].claims) == 2  # nothing changed


class TestCritiqueSuccess:
    @pytest.mark.asyncio
    async def test_critique_drops_unanchored_claim(self, monkeypatch) -> None:
        monkeypatch.setattr(critique_mod, "_ANTHROPIC_API_KEY", "key")
        client = _stub_post({
            "content": [{
                "type": "tool_use",
                "name": "emit_critique",
                "input": {
                    "actions": [{
                        "action": "drop_claim",
                        "section_id": "chief_complaint",
                        "claim_id": "claim_bad",
                        "reason": "source_id seg_999 not in transcript",
                    }, {
                        "action": "set_section_status",
                        "section_id": "plan",
                        "new_status": "not_captured",
                        "reason": "no claims",
                    }]
                },
            }]
        })
        with patch("httpx.AsyncClient", return_value=client):
            note = _note()
            out = await critique_note(note, _transcript())
        # Bad claim dropped
        ids = [c.id for c in out.sections[0].claims]
        assert ids == ["claim_001"]
        # Plan flipped
        plan = next(s for s in out.sections if s.id == "plan")
        assert plan.status == "not_captured"

    @pytest.mark.asyncio
    async def test_critique_request_uses_tool_choice(self, monkeypatch) -> None:
        monkeypatch.setattr(critique_mod, "_ANTHROPIC_API_KEY", "key")
        client = _stub_post({
            "content": [{
                "type": "tool_use",
                "name": "emit_critique",
                "input": {"actions": []},
            }]
        })
        with patch("httpx.AsyncClient", return_value=client):
            await critique_note(_note(), _transcript())
        body = client.post.await_args.kwargs["json"]
        assert body["tool_choice"] == {"type": "tool", "name": "emit_critique"}
        assert body["tools"][0]["name"] == "emit_critique"
