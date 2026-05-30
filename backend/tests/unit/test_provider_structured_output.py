"""Verify Tier 1 / item B — structured output is enforced on Anthropic
(tool_use with input_schema) and Gemini (responseSchema in generationConfig).

OpenAI already had `response_format: json_object` and is unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.providers.note_gen.shared import NOTE_RESPONSE_SCHEMA
from app.modules.providers.vision.shared import VISION_RESPONSE_SCHEMA


def _stub_post(json_payload: dict) -> tuple[AsyncMock, MagicMock]:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_payload)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client, response


# ── Anthropic uses tool_use + tool_choice ──────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_note_uses_tool_use(monkeypatch) -> None:
    from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
    from app.modules.providers.note_gen import anthropic as a

    monkeypatch.setattr(a, "_ANTHROPIC_API_KEY", "key")

    # Tool-use response (the path we expect Anthropic to take).
    client, _ = _stub_post({
        "content": [
            {
                "type": "tool_use",
                "name": "emit_clinical_note",
                "input": {"sections": []},
            }
        ]
    })
    with patch("httpx.AsyncClient", return_value=client), \
         patch("app.modules.providers.note_gen.anthropic.parse_note_response",
               return_value="ok"):
        await a.AnthropicNoteGenerationProvider().generate_note(
            transcript=Transcript(session_id="s", provider_used="t", segments=[
                TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hi")
            ]),
            template=Template(key="general", display_name="General",
                              sections=[TemplateSection(id="cc", title="CC")]),
            stage=1,
        )

    body = client.post.await_args.kwargs["json"]
    # Tool definition is present + pinned via tool_choice.
    assert "tools" in body
    assert body["tools"][0]["name"] == "emit_clinical_note"
    assert body["tools"][0]["input_schema"] == NOTE_RESPONSE_SCHEMA
    assert body["tool_choice"] == {"type": "tool", "name": "emit_clinical_note"}


@pytest.mark.asyncio
async def test_anthropic_vision_uses_tool_use(monkeypatch) -> None:
    from app.core.types import MaskedFrame, TranscriptSegment
    from app.modules.providers.vision import anthropic as av

    monkeypatch.setattr(av, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(
        "app.modules.providers.vision.anthropic.load_frame_image_base64",
        AsyncMock(return_value="aGVsbG8="),
    )

    client, _ = _stub_post({
        "content": [
            {
                "type": "tool_use",
                "name": "emit_frame_caption",
                "input": {
                    "description": "ok",
                    "confidence": "high",
                    "confidence_reason": "clear",
                },
            }
        ]
    })
    with patch("httpx.AsyncClient", return_value=client):
        await av.AnthropicVisionProvider().caption_frame(
            frame=MaskedFrame(frame_id="f", session_id="s",
                              timestamp_ms=0, s3_key="k",
                              masking_confirmed=True),
            anchor=TranscriptSegment(id="seg", start_ms=0, end_ms=10, text="t"),
        )

    body = client.post.await_args.kwargs["json"]
    assert body["tools"][0]["name"] == "emit_frame_caption"
    assert body["tools"][0]["input_schema"] == VISION_RESPONSE_SCHEMA
    assert body["tool_choice"] == {"type": "tool", "name": "emit_frame_caption"}


# ── Gemini uses responseSchema ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_gemini_note_sets_response_schema(monkeypatch) -> None:
    from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
    from app.modules.providers.note_gen import gemini as g

    monkeypatch.setattr(g, "_GOOGLE_AI_API_KEY", "key")

    client, _ = _stub_post({
        "candidates": [{"content": {"parts": [{"text": '{"sections": []}'}]}}]
    })
    with patch("httpx.AsyncClient", return_value=client), \
         patch("app.modules.providers.note_gen.gemini.parse_note_response",
               return_value="ok"):
        await g.GeminiNoteGenerationProvider().generate_note(
            transcript=Transcript(session_id="s", provider_used="t", segments=[
                TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hi")
            ]),
            template=Template(key="general", display_name="General",
                              sections=[TemplateSection(id="cc", title="CC")]),
            stage=1,
        )

    cfg = client.post.await_args.kwargs["json"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"] == NOTE_RESPONSE_SCHEMA


@pytest.mark.asyncio
async def test_gemini_vision_sets_response_schema(monkeypatch) -> None:
    from app.core.types import MaskedFrame, TranscriptSegment
    from app.modules.providers.vision import gemini as gv

    monkeypatch.setattr(gv, "_GOOGLE_AI_API_KEY", "key")
    monkeypatch.setattr(
        "app.modules.providers.vision.gemini.load_frame_image_base64",
        AsyncMock(return_value="aGVsbG8="),
    )

    client, _ = _stub_post({
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"description": "ok", "confidence": "high",'
                            ' "confidence_reason": "clear"}'
                }]
            }
        }]
    })
    with patch("httpx.AsyncClient", return_value=client):
        await gv.GeminiVisionProvider().caption_frame(
            frame=MaskedFrame(frame_id="f", session_id="s",
                              timestamp_ms=0, s3_key="k",
                              masking_confirmed=True),
            anchor=TranscriptSegment(id="seg", start_ms=0, end_ms=10, text="t"),
        )

    cfg = client.post.await_args.kwargs["json"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"] == VISION_RESPONSE_SCHEMA
