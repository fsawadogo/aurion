"""Stage-2 captioning is concurrency-bounded (vision_max_concurrency).

The captioning fan-out previously fired one Gemini request per frame with no
bound, so a large frame set hit the vision rate limit all at once — every call
429'd, the backoff retried them together, and almost no captions survived (a
note came back audio-only). A semaphore now caps how many frames caption at
once. This test locks that the peak in-flight count never exceeds the config
value, so frames drain under the rate limit instead of storming it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.vision.service as vision_service
from app.core.types import FrameCaption, MaskedFrame, TranscriptSegment
from app.modules.config.schema import AppConfigSchema


def _frame(i: int) -> MaskedFrame:
    return MaskedFrame(
        frame_id=f"frame_{i:03d}",
        session_id="s1",
        timestamp_ms=1000 + i * 100,
        s3_key=f"frames/s1/{1000 + i * 100}.jpg",
        masking_confirmed=True,
    )


def _caption(frame_id: str) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="s1",
        timestamp_ms=1000,
        audio_anchor_id="seg_001",
        provider_used="gemini",
        visual_description="Reduced knee flexion, reaches ~110 degrees.",
        confidence="high",
        confidence_reason="clear view",
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
    )


def _config_with_concurrency(limit: int) -> AppConfigSchema:
    cfg = AppConfigSchema()
    return cfg.model_copy(
        update={"pipeline": cfg.pipeline.model_copy(update={"vision_max_concurrency": limit})}
    )


@pytest.mark.asyncio
async def test_captioning_never_exceeds_configured_concurrency() -> None:
    limit = 3
    n_frames = 12
    state = {"in_flight": 0, "peak": 0}

    async def fake_caption_frame(*args, **kwargs) -> FrameCaption:
        frame = args[0]
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        try:
            await asyncio.sleep(0.02)  # hold the slot so overlap is observable
            return _caption(frame.frame_id)
        finally:
            state["in_flight"] -= 1

    provider = MagicMock()
    provider.caption_frame = AsyncMock(side_effect=fake_caption_frame)
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(return_value=provider)

    trigger = TranscriptSegment(
        id="seg_001", start_ms=1000, end_ms=2000, text="range of motion",
        is_visual_trigger=True, trigger_type="active_physical_examination",
    )

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=AsyncMock()),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
        patch.object(
            vision_service, "get_config", return_value=_config_with_concurrency(limit)
        ),
    ):
        captions = await vision_service.caption_visual_evidence(
            evidence=[_frame(i) for i in range(n_frames)],
            trigger_segments=[trigger],
        )

    # All frames still captioned (the cap paces them, never drops them)…
    assert len(captions) == n_frames
    assert provider.caption_frame.await_count == n_frames
    # …but never more than `limit` were in flight at once.
    assert state["peak"] <= limit
    assert state["peak"] > 1  # sanity: they did overlap (not fully serial)
