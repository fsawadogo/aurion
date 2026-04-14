"""Tests for reliability hardening — retry wrapper, vision fallback, cleanup verification."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.retry import with_retry


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_client_error(code: str, message: str = "error") -> ClientError:
    """Build a botocore ClientError with the given error code."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "TestOperation",
    )


# ── Retry wrapper tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    """Function fails once with a retryable error, then succeeds."""
    fn = MagicMock(side_effect=[_make_client_error("503"), "ok"])

    with patch("app.core.retry.asyncio.sleep", new_callable=AsyncMock):
        result = await with_retry(
            fn, max_retries=3, base_delay=0.01, operation="test_op"
        )

    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
async def test_retry_exhaustion_raises():
    """Function always fails — exception raised after max_retries attempts."""
    error = _make_client_error("503", "service unavailable")
    fn = MagicMock(side_effect=error)

    with patch("app.core.retry.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ClientError) as exc_info:
            await with_retry(
                fn, max_retries=3, base_delay=0.01, operation="test_op"
            )

    assert "service unavailable" in str(exc_info.value)
    # Initial attempt + 3 retries = 4 total calls
    assert fn.call_count == 4


@pytest.mark.asyncio
async def test_retry_skips_non_retryable():
    """Non-retryable error (403) is raised immediately without retry."""
    error = _make_client_error("403", "forbidden")
    fn = MagicMock(side_effect=error)

    with patch("app.core.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(ClientError) as exc_info:
            await with_retry(
                fn, max_retries=3, base_delay=0.01, operation="test_op"
            )

    assert "forbidden" in str(exc_info.value)
    # Only the initial attempt — no retries
    assert fn.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_exponential_backoff():
    """Verify delay increases exponentially between retries."""
    error = _make_client_error("503")
    fn = MagicMock(side_effect=[error, error, error, "ok"])

    sleep_delays: list[float] = []

    async def capture_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    with patch("app.core.retry.asyncio.sleep", side_effect=capture_sleep):
        with patch("app.core.retry.random.uniform", return_value=0.0):
            result = await with_retry(
                fn, max_retries=3, base_delay=1.0, operation="test_op"
            )

    assert result == "ok"
    assert len(sleep_delays) == 3
    # With jitter=0: delay = base_delay * 2^attempt → 1.0, 2.0, 4.0
    assert sleep_delays[0] == pytest.approx(1.0)
    assert sleep_delays[1] == pytest.approx(2.0)
    assert sleep_delays[2] == pytest.approx(4.0)


# ── Vision fallback test ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vision_fallback_used_when_primary_fails():
    """When the primary vision provider raises, the fallback provider is used."""
    from app.core.types import FrameCaption, MaskedFrame, ProviderError, TranscriptSegment

    frame = MaskedFrame(
        frame_id="frame_00100",
        session_id="test-session",
        timestamp_ms=1000,
        s3_key="frames/test-session/1000.jpg",
        masking_confirmed=True,
    )
    segment = TranscriptSegment(
        id="seg_001",
        start_ms=800,
        end_ms=1200,
        text="tenderness on palpation",
        is_visual_trigger=True,
        trigger_type="active_physical_examination",
    )
    fallback_caption = FrameCaption(
        frame_id="frame_00100",
        session_id="test-session",
        timestamp_ms=1000,
        audio_anchor_id="seg_001",
        provider_used="anthropic",
        visual_description="Patient arm elevated",
        confidence="high",
        integration_status="ENRICHES",
    )

    # Primary raises, fallback succeeds
    primary_provider = AsyncMock()
    primary_provider.caption_frame = AsyncMock(
        side_effect=ProviderError("openai", "API timeout")
    )
    fallback_provider = AsyncMock()
    fallback_provider.caption_frame = AsyncMock(return_value=fallback_caption)

    mock_registry = MagicMock()
    # First call returns primary (used in the initial caption_frames setup),
    # subsequent calls return the fallback
    mock_registry.get_vision_provider_with_fallback = MagicMock(
        side_effect=[primary_provider, fallback_provider]
    )

    mock_audit = AsyncMock()
    mock_audit.write_event = AsyncMock()

    with (
        patch(
            "app.modules.vision.service.get_registry",
            return_value=mock_registry,
        ),
        patch(
            "app.modules.vision.service.get_audit_log_service",
            return_value=mock_audit,
        ),
    ):
        from app.modules.vision.service import caption_frames

        result = await caption_frames([frame], [segment])

    assert len(result) == 1
    assert result[0].provider_used == "anthropic"
    # Verify provider_fallback audit event was logged
    audit_events = [
        call.kwargs.get("event_type") or call.args[0]
        for call in mock_audit.write_event.call_args_list
    ]
    assert "provider_fallback" in [
        call[1]["event_type"]
        for call in mock_audit.write_event.call_args_list
        if "event_type" in call[1]
    ]


# ── Cleanup verification tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_verify_purge_empty_bucket():
    """verify_purge returns True when no objects remain in either bucket."""
    mock_client = MagicMock()
    mock_client.list_objects_v2 = MagicMock(return_value={"KeyCount": 0})

    with patch(
        "app.modules.cleanup.service.get_s3_client",
        return_value=mock_client,
    ):
        from app.modules.cleanup.service import verify_purge

        result = await verify_purge("test-session-123")

    assert result is True
    assert mock_client.list_objects_v2.call_count == 2


@pytest.mark.asyncio
async def test_cleanup_verify_purge_with_remaining():
    """verify_purge returns False when objects still exist in a bucket."""
    mock_client = MagicMock()
    # Audio bucket is empty, frames bucket still has objects
    mock_client.list_objects_v2 = MagicMock(
        side_effect=[
            {"KeyCount": 0},  # audio bucket empty
            {"Contents": [{"Key": "test-session-123/frame001.jpg"}]},  # frames remain
        ]
    )

    with patch(
        "app.modules.cleanup.service.get_s3_client",
        return_value=mock_client,
    ):
        from app.modules.cleanup.service import verify_purge

        result = await verify_purge("test-session-123")

    assert result is False
