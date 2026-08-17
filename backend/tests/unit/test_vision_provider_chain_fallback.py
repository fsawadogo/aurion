"""Runtime vision failures advance through distinct providers exactly once."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.vision.service as vision_service
from app.core.audit_events import AuditEventType
from app.core.types import (
    FrameCaption,
    MaskedFrame,
    ProviderError,
    TranscriptSegment,
)
from app.modules.config.schema import AppConfigSchema


def _frame() -> MaskedFrame:
    return MaskedFrame(
        frame_id="frame_001",
        session_id="session-1",
        timestamp_ms=1500,
        s3_key="frames/session-1/1500.jpg",
        masking_confirmed=True,
    )


def _trigger() -> TranscriptSegment:
    return TranscriptSegment(
        id="seg_001",
        start_ms=1000,
        end_ms=2000,
        text="range of motion",
        is_visual_trigger=True,
        trigger_type="active_physical_examination",
    )


def _caption(provider: str) -> FrameCaption:
    return FrameCaption(
        frame_id="frame_001",
        session_id="session-1",
        timestamp_ms=1500,
        audio_anchor_id="seg_001",
        provider_used=provider,
        visual_description="The left knee is flexed during examination.",
        confidence="high",
        confidence_reason="Clear view",
        integration_status="ENRICHES",
    )


def _provider(*, result=None, error: ProviderError | None = None):
    provider = MagicMock()
    if error is not None:
        provider.caption_frame = AsyncMock(side_effect=error)
    else:
        provider.caption_frame = AsyncMock(return_value=result)
    return provider


@pytest.mark.asyncio
async def test_primary_failure_advances_to_distinct_fallback() -> None:
    class GeminiVisionProviderStub:
        def __init__(self) -> None:
            self.caption_frame = AsyncMock(
                side_effect=ProviderError("vision", "rate limited")
            )

    class AnthropicVisionProviderStub:
        def __init__(self) -> None:
            self.caption_frame = AsyncMock(return_value=_caption("anthropic"))

    gemini = GeminiVisionProviderStub()
    anthropic = AnthropicVisionProviderStub()
    registry = SimpleNamespace(get_vision_provider_chain_for_kind=MagicMock(return_value=[gemini, anthropic]))
    audit = AsyncMock()
    usage = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=audit),
        patch.object(vision_service, "try_record_provider_usage", usage),
        patch.object(vision_service, "get_config", return_value=AppConfigSchema()),
    ):
        captions = await vision_service.caption_visual_evidence([_frame()], [_trigger()])

    assert [caption.provider_used for caption in captions] == ["anthropic"]
    assert gemini.caption_frame.await_count == 1
    assert anthropic.caption_frame.await_count == 1
    fallback_events = [
        call
        for call in audit.write_event.await_args_list
        if call.kwargs.get("event_type") == AuditEventType.PROVIDER_FALLBACK
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0].kwargs["fallback_provider"] == "anthropic"
    failure_usage, success_usage = [call.kwargs for call in usage.await_args_list]
    assert failure_usage["provider_name"] == "gemini"
    assert failure_usage["model_name"] == "gemini-2.5-pro"
    assert failure_usage["success"] is False
    assert failure_usage["fallback_used"] is False
    assert success_usage["provider_name"] == "anthropic"
    assert success_usage["model_name"] == "claude-sonnet-4-6"
    assert success_usage["success"] is True
    assert success_usage["fallback_used"] is True
    assert all(call.kwargs["operation"] == "caption_frame" for call in usage.await_args_list)
    assert all(call.kwargs["session_id"] == "session-1" for call in usage.await_args_list)
    assert all(call.kwargs["latency_ms"] >= 0 for call in usage.await_args_list)


@pytest.mark.asyncio
async def test_all_provider_failures_fail_stage2_instead_of_discarding() -> None:
    providers = [_provider(error=ProviderError(name, "unavailable")) for name in ("gemini", "openai", "anthropic")]
    registry = SimpleNamespace(get_vision_provider_chain_for_kind=MagicMock(return_value=providers))
    audit = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=audit),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
        patch.object(vision_service, "try_publish_alert", AsyncMock()),
        patch.object(vision_service, "get_config", return_value=AppConfigSchema()),
    ):
        with pytest.raises(ProviderError, match="All 1 visual evidence"):
            await vision_service.caption_visual_evidence([_frame()], [_trigger()])

    assert [provider.caption_frame.await_count for provider in providers] == [1, 1, 1]
    event_types = [call.kwargs.get("event_type") for call in audit.write_event.await_args_list]
    assert AuditEventType.VISION_FRAME_FAILED in event_types
    # Terminal Stage-2 events belong to the durable job owner, not this shared
    # captioning service (which is also used by admin/eval tooling).
    assert AuditEventType.STAGE2_FAILED not in event_types


@pytest.mark.asyncio
async def test_cancelled_active_attempt_is_recorded_failed_then_propagates() -> None:
    class GeminiVisionProviderStub:
        def __init__(self) -> None:
            self.caption_frame = AsyncMock(side_effect=asyncio.CancelledError())

    provider = GeminiVisionProviderStub()
    registry = SimpleNamespace(
        get_vision_provider_chain_for_kind=MagicMock(return_value=[provider])
    )
    usage = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=AsyncMock()),
        patch.object(vision_service, "try_record_provider_usage", usage),
        patch.object(vision_service, "get_config", return_value=AppConfigSchema()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await vision_service.caption_visual_evidence([_frame()], [_trigger()])

    usage.assert_awaited_once()
    recorded = usage.await_args.kwargs
    assert recorded["provider_type"] == "vision"
    assert recorded["provider_name"] == "gemini"
    assert recorded["model_name"] == "gemini-2.5-pro"
    assert recorded["operation"] == "caption_frame"
    assert recorded["success"] is False
    assert recorded["fallback_used"] is False
    assert recorded["session_id"] == "session-1"
    assert recorded["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_unexpected_model_validation_error_falls_back_without_phi_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_model_text = "Patient Jane Doe has a visible surgical scar"
    primary = _provider(error=None)
    primary.caption_frame = AsyncMock(side_effect=ValueError(sensitive_model_text))
    fallback = _provider(result=_caption("anthropic"))
    registry = SimpleNamespace(
        get_vision_provider_chain_for_kind=MagicMock(
            return_value=[primary, fallback]
        )
    )
    audit = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=audit),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
        patch.object(vision_service, "get_config", return_value=AppConfigSchema()),
        caplog.at_level(logging.WARNING, logger="aurion.vision"),
    ):
        captions = await vision_service.caption_visual_evidence(
            [_frame()], [_trigger()]
        )

    assert [caption.provider_used for caption in captions] == ["anthropic"]
    assert sensitive_model_text not in caplog.text
    fallback_event = next(
        call
        for call in audit.write_event.await_args_list
        if call.kwargs.get("event_type") == AuditEventType.PROVIDER_FALLBACK
    )
    assert fallback_event.kwargs["original_error"].endswith(
        ":provider_attempt_failed"
    )


@pytest.mark.asyncio
async def test_stalled_usage_telemetry_does_not_delay_fallback() -> None:
    primary = _provider(error=ProviderError("gemini", "unavailable"))
    fallback = _provider(result=_caption("anthropic"))
    registry = SimpleNamespace(
        get_vision_provider_chain_for_kind=MagicMock(
            return_value=[primary, fallback]
        )
    )
    spawned: list[asyncio.Task] = []

    async def _stalled_usage(**_kwargs) -> None:
        await asyncio.Event().wait()

    def _spawn(coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        spawned.append(task)
        return task

    try:
        with (
            patch.object(vision_service, "get_registry", return_value=registry),
            patch.object(
                vision_service, "get_audit_log_service", return_value=AsyncMock()
            ),
            patch.object(
                vision_service, "try_record_provider_usage", _stalled_usage
            ),
            patch.object(vision_service, "spawn_background_task", _spawn),
            patch.object(
                vision_service, "get_config", return_value=AppConfigSchema()
            ),
        ):
            async with asyncio.timeout(0.1):
                captions = await vision_service.caption_visual_evidence(
                    [_frame()], [_trigger()]
                )
        assert [caption.provider_used for caption in captions] == ["anthropic"]
        assert fallback.caption_frame.await_count == 1
    finally:
        for task in spawned:
            task.cancel()
        await asyncio.gather(*spawned, return_exceptions=True)


@pytest.mark.asyncio
async def test_stalled_usage_telemetry_does_not_delay_cancellation() -> None:
    started = asyncio.Event()

    async def _active_request(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    provider = _provider(error=None)
    provider.caption_frame = AsyncMock(side_effect=_active_request)
    registry = SimpleNamespace(
        get_vision_provider_chain_for_kind=MagicMock(return_value=[provider])
    )
    spawned: list[asyncio.Task] = []

    async def _stalled_usage(**_kwargs) -> None:
        await asyncio.Event().wait()

    def _spawn(coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        spawned.append(task)
        return task

    try:
        with (
            patch.object(vision_service, "get_registry", return_value=registry),
            patch.object(
                vision_service, "get_audit_log_service", return_value=AsyncMock()
            ),
            patch.object(
                vision_service, "try_record_provider_usage", _stalled_usage
            ),
            patch.object(vision_service, "spawn_background_task", _spawn),
            patch.object(
                vision_service, "get_config", return_value=AppConfigSchema()
            ),
        ):
            caption_task = asyncio.create_task(
                vision_service.caption_visual_evidence([_frame()], [_trigger()])
            )
            await started.wait()
            caption_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                async with asyncio.timeout(0.1):
                    await caption_task
    finally:
        for task in spawned:
            task.cancel()
        await asyncio.gather(*spawned, return_exceptions=True)
