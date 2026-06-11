"""Unit tests for the per-call usage collector (OV-2, #73).

Pins the three properties that make ContextVar the right mechanism:
read-once consumption (stale usage can't attach to a later call),
asyncio-task isolation (concurrent provider calls can't cross-
contaminate), and a clean None default.
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.providers.usage_context import (
    CallUsage,
    consume_call_usage,
    set_call_usage,
)


def test_default_is_none() -> None:
    assert consume_call_usage() is None


def test_set_then_consume_roundtrip_and_clears() -> None:
    set_call_usage(input_tokens=1200, output_tokens=340, model="gpt-4o")
    usage = consume_call_usage()
    assert usage == CallUsage(input_tokens=1200, output_tokens=340, model="gpt-4o")
    # Read-once: a second consume sees nothing.
    assert consume_call_usage() is None


@pytest.mark.asyncio
async def test_concurrent_tasks_are_isolated() -> None:
    """Two provider calls in parallel tasks must each consume their own
    usage — ContextVars are task-local, which is the whole reason this
    isn't mutable state on the shared provider singleton."""

    async def call(model: str, tokens: int) -> CallUsage | None:
        set_call_usage(input_tokens=tokens, output_tokens=tokens, model=model)
        await asyncio.sleep(0.01)  # let the other task interleave
        return consume_call_usage()

    a, b = await asyncio.gather(call("gpt-4o", 100), call("gemini-2.5-pro", 999))
    assert a is not None and a.model == "gpt-4o" and a.input_tokens == 100
    assert b is not None and b.model == "gemini-2.5-pro" and b.input_tokens == 999


def test_audio_cost_rates() -> None:
    """AC-4: whisper (self-hosted) → 0; assemblyai → >0 and hour-scaled;
    unknown provider → 0 fail-soft."""
    from app.core.cost_rates import estimate_audio_cost_usd_micros

    assert estimate_audio_cost_usd_micros("whisper", 3600) == 0
    one_hour = estimate_audio_cost_usd_micros("assemblyai", 3600)
    assert one_hour == 120_000  # $0.12/hr in micros
    assert estimate_audio_cost_usd_micros("assemblyai", 1800) == one_hour // 2
    assert estimate_audio_cost_usd_micros("does-not-exist", 3600) == 0
    assert estimate_audio_cost_usd_micros("assemblyai", 0) == 0
