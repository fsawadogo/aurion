"""Registry-bypassing model calls (critique + reconcile) must record their
tokens/cost to ``provider_usage`` so per-session consumption is COMPLETE.

Before this, the self-critique and Stage-2 reconcile passes fired Anthropic
calls directly (hardcoded endpoint/model, no telemetry), so any per-session
cost undercounted by ~two full Claude calls. These lock: the shared
``record_offline_call`` prices + records; critique + reconcile call it with
the real token counts from the response; and the per-session service returns
the rows.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import (
    FrameCaption,
    Note,
    NoteSection,
    Transcript,
    TranscriptSegment,
)


def _note(provider: str = "anthropic") -> Note:
    return Note(
        session_id="s",
        stage=1,
        provider_used=provider,
        specialty="orthopedic_surgery",
        sections=[NoteSection(id="physical_exam", status="populated")],
    )


def _transcript() -> Transcript:
    return Transcript(
        session_id="s",
        provider_used="whisper",
        segments=[TranscriptSegment(id="seg_0", start_ms=0, end_ms=1, text="x")],
    )


def _async_client_returning(resp):
    """Build a mock that satisfies `async with httpx.AsyncClient(...) as c`."""
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=client)
    acm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=acm)


# ── record_offline_call: prices + records ────────────────────────────────────


@pytest.mark.asyncio
async def test_record_offline_call_prices_and_records() -> None:
    from app.modules.providers import usage_service as us

    svc = MagicMock()
    svc.record = AsyncMock()
    with patch.object(us, "get_provider_usage_service", return_value=svc):
        await us.record_offline_call(
            MagicMock(),
            provider_type="note_generation",
            provider_name="anthropic",
            model="claude-sonnet-4-6",
            operation="critique_note",
            input_tokens=1000,
            output_tokens=200,
            latency_ms=500,
            session_id=uuid.uuid4(),
        )
    svc.record.assert_awaited_once()
    kw = svc.record.await_args.kwargs
    assert kw["input_tokens"] == 1000
    assert kw["output_tokens"] == 200
    assert kw["operation"] == "critique_note"
    assert kw["model_name"] == "claude-sonnet-4-6"
    # $3/MT in + $15/MT out → 1000*3/1e6 + 200*15/1e6 = 0.003 + 0.003 = 0.006
    assert abs(kw["cost_usd"] - 0.006) < 1e-9


# ── critique_note records its usage when db + session_id are passed ──────────


@pytest.mark.asyncio
async def test_critique_records_usage_when_db_provided() -> None:
    from app.modules.note_gen import critique as cq

    resp = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "usage": {"input_tokens": 1200, "output_tokens": 300},
            "content": [
                {"type": "tool_use", "name": "emit_critique",
                 "input": {"actions": []}}
            ],
        },
    )
    sid = str(uuid.uuid4())
    with patch.object(cq, "_ANTHROPIC_API_KEY", "k"), patch.object(
        cq.httpx, "AsyncClient", _async_client_returning(resp)
    ), patch(
        "app.modules.providers.usage_service.record_offline_call",
        new_callable=AsyncMock,
    ) as rec:
        await cq.critique_note(
            _note(), _transcript(), db=MagicMock(), session_id=sid
        )
    rec.assert_awaited_once()
    kw = rec.await_args.kwargs
    assert kw["provider_name"] == "anthropic"
    assert kw["operation"] == "critique_note"
    assert kw["input_tokens"] == 1200
    assert kw["output_tokens"] == 300


@pytest.mark.asyncio
async def test_critique_no_db_records_nothing() -> None:
    """Back-compat: called without db (tests / other callers) → no telemetry,
    no crash."""
    from app.modules.note_gen import critique as cq

    resp = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"usage": {}, "content": [
            {"type": "tool_use", "name": "emit_critique", "input": {"actions": []}}
        ]},
    )
    with patch.object(cq, "_ANTHROPIC_API_KEY", "k"), patch.object(
        cq.httpx, "AsyncClient", _async_client_returning(resp)
    ), patch(
        "app.modules.providers.usage_service.record_offline_call",
        new_callable=AsyncMock,
    ) as rec:
        await cq.critique_note(_note(), _transcript())
    rec.assert_not_awaited()


# ── reconcile_captions records its usage when db + session_id are passed ─────


@pytest.mark.asyncio
async def test_reconcile_records_usage_when_db_provided() -> None:
    from app.modules.vision import reconcile as rc

    caption = FrameCaption(
        frame_id="frame_1",
        session_id="s",
        timestamp_ms=1000,
        audio_anchor_id="seg_0",
        provider_used="gemini",
        visual_description="knee flexed",
        confidence="high",
        integration_status="ENRICHES",
    )
    resp = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "usage": {"input_tokens": 900, "output_tokens": 150},
            "content": [
                {"type": "tool_use", "name": "emit_reconciliation",
                 "input": {"decisions": []}}
            ],
        },
    )
    sid = str(uuid.uuid4())
    with patch.object(rc, "_ANTHROPIC_API_KEY", "k"), patch.object(
        rc.httpx, "AsyncClient", _async_client_returning(resp)
    ), patch(
        "app.modules.providers.usage_service.record_offline_call",
        new_callable=AsyncMock,
    ) as rec:
        await rc.reconcile_captions(
            [caption], _note(), db=MagicMock(), session_id=sid
        )
    rec.assert_awaited_once()
    kw = rec.await_args.kwargs
    assert kw["operation"] == "reconcile_captions"
    assert kw["input_tokens"] == 900
    assert kw["output_tokens"] == 150


# ── by_session returns the per-call rows ─────────────────────────────────────


@pytest.mark.asyncio
async def test_by_session_returns_rows() -> None:
    from app.modules.providers.usage_service import ProviderUsageService

    row_a = SimpleNamespace(operation="generate_note")
    row_b = SimpleNamespace(operation="critique_note")
    result = MagicMock()
    result.scalars.return_value = SimpleNamespace(all=lambda: [row_a, row_b])
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    rows = await ProviderUsageService().by_session(db, uuid.uuid4())
    assert [r.operation for r in rows] == ["generate_note", "critique_note"]
