"""Unit tests for the Stage 2 reconciliation LLM call (Tier 1 / item C).

Verifies:
- No API key → no-op (preserves existing integration_status)
- LLM failure → no-op (best-effort)
- Successful tool_use response → captions updated per the decisions
- Conflict detail propagates onto the caption
- Empty captions → fast return
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import (
    FrameCaption,
    Note,
    NoteClaim,
    NoteSection,
)
from app.modules.vision import reconcile as reconcile_mod
from app.modules.vision.reconcile import reconcile_captions


def _caption(
    frame_id: str = "frame_001",
    anchor_id: str = "seg_001",
    description: str = "Visible swelling",
    initial_status: str = "REPEATS",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="s",
        timestamp_ms=1000,
        audio_anchor_id=anchor_id,
        provider_used="anthropic",
        visual_description=description,
        confidence="high",
        confidence_reason="",
        conflict_flag=False,
        conflict_detail=None,
        integration_status=initial_status,
    )


def _note() -> Note:
    return Note(
        session_id="s",
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="physical_exam",
                title="Physical Exam",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_001",
                        text="Physician noted small effusion",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="There's a small effusion.",
                    ),
                ],
            ),
        ],
        completeness_score=1.0,
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


class TestNoOpPaths:
    @pytest.mark.asyncio
    async def test_empty_captions_returns_immediately(self) -> None:
        result = await reconcile_captions([], _note())
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_api_key_preserves_status(self, monkeypatch) -> None:
        monkeypatch.setattr(reconcile_mod, "_ANTHROPIC_API_KEY", "")
        caps = [_caption(initial_status="ENRICHES")]
        out = await reconcile_captions(caps, _note())
        # Untouched
        assert out[0].integration_status == "ENRICHES"

    @pytest.mark.asyncio
    async def test_llm_error_preserves_status(self, monkeypatch) -> None:
        monkeypatch.setattr(reconcile_mod, "_ANTHROPIC_API_KEY", "key")

        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("network down"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=client):
            caps = [_caption(initial_status="REPEATS")]
            out = await reconcile_captions(caps, _note())
        assert out[0].integration_status == "REPEATS"
        assert out[0].conflict_flag is False


class TestSuccessfulReconciliation:
    @pytest.mark.asyncio
    async def test_enriches_decision_updates_caption(self, monkeypatch) -> None:
        monkeypatch.setattr(reconcile_mod, "_ANTHROPIC_API_KEY", "key")
        client = _stub_post({
            "content": [{
                "type": "tool_use",
                "name": "emit_reconciliation",
                "input": {
                    "decisions": [
                        {"frame_id": "frame_001", "status": "ENRICHES"}
                    ]
                },
            }]
        })
        with patch("httpx.AsyncClient", return_value=client):
            caps = [_caption(initial_status="REPEATS")]
            out = await reconcile_captions(caps, _note())
        assert out[0].integration_status == "ENRICHES"
        assert out[0].conflict_flag is False

    @pytest.mark.asyncio
    async def test_conflicts_decision_sets_flag_and_detail(self, monkeypatch) -> None:
        monkeypatch.setattr(reconcile_mod, "_ANTHROPIC_API_KEY", "key")
        client = _stub_post({
            "content": [{
                "type": "tool_use",
                "name": "emit_reconciliation",
                "input": {
                    "decisions": [{
                        "frame_id": "frame_001",
                        "status": "CONFLICTS",
                        "conflict_detail": "audio said no swelling, frame shows visible swelling",
                    }]
                },
            }]
        })
        with patch("httpx.AsyncClient", return_value=client):
            caps = [_caption(initial_status="REPEATS")]
            out = await reconcile_captions(caps, _note())
        assert out[0].integration_status == "CONFLICTS"
        assert out[0].conflict_flag is True
        assert out[0].conflict_detail and "swelling" in out[0].conflict_detail

    @pytest.mark.asyncio
    async def test_missing_decision_leaves_caption_alone(self, monkeypatch) -> None:
        """A frame the LLM didn't return a decision for keeps its current status."""
        monkeypatch.setattr(reconcile_mod, "_ANTHROPIC_API_KEY", "key")
        client = _stub_post({
            "content": [{
                "type": "tool_use",
                "name": "emit_reconciliation",
                "input": {
                    "decisions": [
                        {"frame_id": "frame_002", "status": "ENRICHES"}
                    ]
                },
            }]
        })
        with patch("httpx.AsyncClient", return_value=client):
            caps = [
                _caption(frame_id="frame_001", initial_status="REPEATS"),
                _caption(frame_id="frame_002", initial_status="REPEATS"),
            ]
            out = await reconcile_captions(caps, _note())
        # frame_001 untouched
        assert out[0].integration_status == "REPEATS"
        # frame_002 updated
        assert out[1].integration_status == "ENRICHES"

    @pytest.mark.asyncio
    async def test_prompt_includes_note_claims_per_anchor(self, monkeypatch) -> None:
        """The user prompt builder must surface the audio claims that share
        the caption's anchor so the model can actually compare."""
        monkeypatch.setattr(reconcile_mod, "_ANTHROPIC_API_KEY", "key")
        client = _stub_post({
            "content": [{
                "type": "tool_use",
                "name": "emit_reconciliation",
                "input": {"decisions": []},
            }]
        })
        with patch("httpx.AsyncClient", return_value=client):
            await reconcile_captions(
                [_caption(anchor_id="seg_001")], _note()
            )
        body = client.post.await_args.kwargs["json"]
        user_msg = body["messages"][0]["content"]
        assert "frame_001" in user_msg
        assert "seg_001" in user_msg
        assert "small effusion" in user_msg
        # Schema-enforced output configured
        assert body["tools"][0]["name"] == "emit_reconciliation"
        assert body["tool_choice"] == {"type": "tool", "name": "emit_reconciliation"}
