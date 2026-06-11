"""OV-2 (#73): note_gen providers surface token usage; the service prices
and records it.

Provider side (AC-2): each provider's response parsing sets the ContextVar
from its own wire shape (anthropic ``usage``, openai ``usage``, gemini
``usageMetadata``) — exercised by calling the real extraction code path
with a canned response via a mocked httpx client.

Service side (AC-3): `_record_provider_usage` consumes the usage, prices
it via the shared core rate sheet, and feeds tokens/model/cost into
``ProviderUsageService.record`` — and consumes even on failure so stale
tokens never attach to a later call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.providers.usage_context import (
    consume_call_usage,
    set_call_usage,
)


@pytest.fixture(autouse=True)
def _clean_context():
    consume_call_usage()
    yield
    consume_call_usage()


def _mock_async_client(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


def _note_json() -> str:
    return (
        '{"sections": [{"id": "chief_complaint", "status": "populated",'
        ' "claims": []}]}'
    )


def _transcript() -> MagicMock:
    t = MagicMock()
    t.session_id = "11111111-2222-3333-4444-555555555555"
    t.segments = []
    return t


def _template() -> MagicMock:
    tpl = MagicMock()
    tpl.key = "general"
    tpl.sections = []
    return tpl


# ── AC-2: provider-side capture per wire shape ───────────────────────────────


@pytest.mark.asyncio
async def test_openai_sets_usage_from_response(monkeypatch) -> None:
    from app.modules.providers.note_gen import openai as mod

    payload = {
        "choices": [{"message": {"content": _note_json()}}],
        "usage": {"prompt_tokens": 1500, "completion_tokens": 420},
    }
    with patch.object(mod, "_OPENAI_API_KEY", "test-key"), \
         patch.object(mod.httpx, "AsyncClient", return_value=_mock_async_client(payload)), \
         patch.object(mod, "parse_note_response", return_value=MagicMock()):
        await mod.OpenAINoteGenerationProvider().generate_note(
            _transcript(), _template(), 1
        )

    usage = consume_call_usage()
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (1500, 420)
    assert usage.model == mod._MODEL


@pytest.mark.asyncio
async def test_gemini_sets_usage_from_response() -> None:
    from app.modules.providers.note_gen import gemini as mod

    payload = {
        "candidates": [{"content": {"parts": [{"text": _note_json()}]}}],
        "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 210},
    }
    with patch.object(mod, "_GOOGLE_AI_API_KEY", "test-key"), \
         patch.object(mod.httpx, "AsyncClient", return_value=_mock_async_client(payload)), \
         patch.object(mod, "parse_note_response", return_value=MagicMock()):
        await mod.GeminiNoteGenerationProvider().generate_note(_transcript(), _template(), 1)

    usage = consume_call_usage()
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (900, 210)
    assert usage.model == mod._MODEL


@pytest.mark.asyncio
async def test_anthropic_sets_usage_from_response() -> None:
    from app.modules.providers.note_gen import anthropic as mod

    payload = {
        "content": [
            {"type": "tool_use", "name": "emit_clinical_note", "input": {"sections": []}}
        ],
        "usage": {"input_tokens": 2200, "output_tokens": 650},
    }
    with patch.object(mod, "_ANTHROPIC_API_KEY", "test-key"), \
         patch.object(mod.httpx, "AsyncClient", return_value=_mock_async_client(payload)), \
         patch.object(mod, "parse_note_response", return_value=MagicMock()):
        await mod.AnthropicNoteGenerationProvider().generate_note(_transcript(), _template(), 1)

    usage = consume_call_usage()
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (2200, 650)
    assert usage.model == mod._MODEL


# ── AC-3: service-side pricing + record ──────────────────────────────────────


@pytest.mark.asyncio
async def test_record_helper_prices_and_records_usage(monkeypatch) -> None:
    from app.modules.note_gen import service as ng

    svc = MagicMock()
    svc.record = AsyncMock()
    monkeypatch.setattr(ng, "get_provider_usage_service", lambda: svc)

    set_call_usage(input_tokens=1_000_000, output_tokens=0, model="gpt-4o")
    await ng._record_provider_usage(
        db=AsyncMock(),
        provider_type="note_generation",
        provider_name="openai",
        operation="generate_note",
        latency_ms=1234,
        success=True,
        session_id=None,
    )

    kwargs = svc.record.call_args.kwargs
    assert kwargs["input_tokens"] == 1_000_000
    assert kwargs["output_tokens"] == 0
    assert kwargs["model_name"] == "gpt-4o"
    # 1M input tokens of gpt-4o at $2.50/MT.
    assert kwargs["cost_usd"] == pytest.approx(2.50)
    # Read-once: the helper consumed it.
    assert consume_call_usage() is None


@pytest.mark.asyncio
async def test_record_helper_consumes_on_failure_without_pricing(monkeypatch) -> None:
    """A failed call still clears the context (no stale attribution) but
    records no cost — we don't price calls that didn't deliver."""
    from app.modules.note_gen import service as ng

    svc = MagicMock()
    svc.record = AsyncMock()
    monkeypatch.setattr(ng, "get_provider_usage_service", lambda: svc)

    set_call_usage(input_tokens=500, output_tokens=0, model="gpt-4o")
    await ng._record_provider_usage(
        db=AsyncMock(),
        provider_type="note_generation",
        provider_name="openai",
        operation="generate_note",
        latency_ms=50,
        success=False,
        session_id=None,
    )

    kwargs = svc.record.call_args.kwargs
    assert kwargs["cost_usd"] is None
    assert consume_call_usage() is None
