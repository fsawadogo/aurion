"""Verify the 6 AI providers actually read temperature + max_tokens from
AppConfig at call time (Tier 1 / item A in the LLM-intelligence upgrade).

Pre-refactor these were hardcoded — changing AppConfig would not have
flowed through to the wire payload. Pin the behaviour now so the live
configurability documented in CLAUDE.md §"Runtime Configuration" stays
true.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.config.schema import (
    AppConfigSchema,
    ModelParamsConfig,
    NoteGenerationModelParams,
    VisionModelParams,
)


def _custom_config(
    note_temp: float = 0.42,
    note_max: int = 1234,
    vision_temp: float = 0.33,
    vision_max: int = 777,
) -> AppConfigSchema:
    """Build an AppConfig with values that no provider would hardcode."""
    return AppConfigSchema(
        model_params=ModelParamsConfig(
            note_generation=NoteGenerationModelParams(
                temperature=note_temp, max_tokens=note_max
            ),
            vision=VisionModelParams(
                temperature=vision_temp, max_tokens=vision_max
            ),
        )
    )


def _stub_httpx_post(json_payload: dict) -> tuple[AsyncMock, MagicMock]:
    """An AsyncMock httpx client whose .post returns a synthetic response.
    Returns (client_mock, response_mock) so the caller can inspect calls.
    """
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_payload)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client, response


# ── note generation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_note_reads_appconfig_params(monkeypatch) -> None:
    from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
    from app.modules.providers.note_gen import openai as oai

    monkeypatch.setattr(oai, "_OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "app.modules.providers.note_gen.openai.get_config",
        lambda: _custom_config(note_temp=0.42, note_max=1234),
    )

    client, _ = _stub_httpx_post({
        "choices": [{"message": {"content": '{"sections": []}'}}]
    })
    with patch("httpx.AsyncClient", return_value=client), \
         patch("app.modules.providers.note_gen.openai.parse_note_response",
               return_value="ok"):
        await oai.OpenAINoteGenerationProvider().generate_note(
            transcript=Transcript(session_id="s", provider_used="t", segments=[
                TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hi")
            ]),
            template=Template(key="general", display_name="General",
                              sections=[TemplateSection(id="cc", title="CC")]),
            stage=1,
        )

    body = client.post.await_args.kwargs["json"]
    assert body["temperature"] == 0.42
    assert body["max_tokens"] == 1234


@pytest.mark.asyncio
async def test_anthropic_note_reads_appconfig_params(monkeypatch) -> None:
    from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
    from app.modules.providers.note_gen import anthropic as a

    monkeypatch.setattr(a, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(
        "app.modules.providers.note_gen.anthropic.get_config",
        lambda: _custom_config(note_temp=0.42, note_max=1234),
    )

    client, _ = _stub_httpx_post({
        "content": [{"type": "text", "text": '{"sections": []}'}]
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
    assert body["temperature"] == 0.42
    assert body["max_tokens"] == 1234


@pytest.mark.asyncio
async def test_gemini_note_reads_appconfig_params(monkeypatch) -> None:
    from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
    from app.modules.providers.note_gen import gemini as g

    monkeypatch.setattr(g, "_GOOGLE_AI_API_KEY", "key")
    monkeypatch.setattr(
        "app.modules.providers.note_gen.gemini.get_config",
        lambda: _custom_config(note_temp=0.42, note_max=1234),
    )

    client, _ = _stub_httpx_post({
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
    assert cfg["temperature"] == 0.42
    assert cfg["maxOutputTokens"] == 1234


# ── vision ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_vision_reads_appconfig_params(monkeypatch) -> None:
    from app.core.types import MaskedFrame, TranscriptSegment
    from app.modules.providers.vision import openai as ov

    monkeypatch.setattr(ov, "_OPENAI_API_KEY", "sk")
    monkeypatch.setattr(
        "app.modules.providers.vision.openai.get_config",
        lambda: _custom_config(vision_temp=0.33, vision_max=777),
    )
    monkeypatch.setattr(
        "app.modules.providers.vision.openai.load_frame_image_base64",
        AsyncMock(return_value="aGVsbG8="),
    )

    client, _ = _stub_httpx_post({
        "choices": [{
            "message": {
                "content": '{"description": "ok", "confidence": "high",'
                           ' "confidence_reason": "clear"}'
            }
        }]
    })
    with patch("httpx.AsyncClient", return_value=client):
        await ov.OpenAIVisionProvider().caption_frame(
            frame=MaskedFrame(frame_id="f", session_id="s",
                              timestamp_ms=0, s3_key="k",
                              masking_confirmed=True),
            anchor=TranscriptSegment(id="seg", start_ms=0, end_ms=10, text="t"),
        )
    body = client.post.await_args.kwargs["json"]
    assert body["temperature"] == 0.33
    assert body["max_tokens"] == 777


@pytest.mark.asyncio
async def test_anthropic_vision_reads_appconfig_params(monkeypatch) -> None:
    from app.core.types import MaskedFrame, TranscriptSegment
    from app.modules.providers.vision import anthropic as av

    monkeypatch.setattr(av, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(
        "app.modules.providers.vision.anthropic.get_config",
        lambda: _custom_config(vision_temp=0.33, vision_max=777),
    )
    monkeypatch.setattr(
        "app.modules.providers.vision.anthropic.load_frame_image_base64",
        AsyncMock(return_value="aGVsbG8="),
    )

    client, _ = _stub_httpx_post({
        "content": [{
            "type": "text",
            "text": '{"description": "ok", "confidence": "high",'
                    ' "confidence_reason": "clear"}'
        }]
    })
    with patch("httpx.AsyncClient", return_value=client):
        await av.AnthropicVisionProvider().caption_frame(
            frame=MaskedFrame(frame_id="f", session_id="s",
                              timestamp_ms=0, s3_key="k",
                              masking_confirmed=True),
            anchor=TranscriptSegment(id="seg", start_ms=0, end_ms=10, text="t"),
        )
    body = client.post.await_args.kwargs["json"]
    assert body["temperature"] == 0.33
    assert body["max_tokens"] == 777


@pytest.mark.asyncio
async def test_gemini_vision_reads_appconfig_params(monkeypatch) -> None:
    from app.core.types import MaskedFrame, TranscriptSegment
    from app.modules.providers.vision import gemini as gv

    monkeypatch.setattr(gv, "_GOOGLE_AI_API_KEY", "key")
    monkeypatch.setattr(
        "app.modules.providers.vision.gemini.get_config",
        lambda: _custom_config(vision_temp=0.33, vision_max=777),
    )
    monkeypatch.setattr(
        "app.modules.providers.vision.gemini.load_frame_image_base64",
        AsyncMock(return_value="aGVsbG8="),
    )

    client, _ = _stub_httpx_post({
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
    assert cfg["temperature"] == 0.33
    assert cfg["maxOutputTokens"] == 777
