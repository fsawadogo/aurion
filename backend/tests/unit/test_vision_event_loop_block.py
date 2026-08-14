"""Stage 2's S3 access must not block the event loop.

`with_retry` invokes its callable directly (`result = fn(...)`, awaited only
if it returns a coroutine), so a SYNCHRONOUS boto3 call runs inline on the
loop. `vision/service.py` drives boto3 that way, so every `list_objects_v2` /
`head_object` in Stage 2 stalls the whole worker.

Why that is a user-visible bug and not just a latency nit: Stage 2 is spawned
as a background task by `POST /notes/{id}/approve-stage1`. While it blocks,
that route's response cannot be flushed, the ALB eventually returns a gateway
502/504 — and an ALB error response carries no CORS headers, so the browser
reports "blocked by CORS policy" and the real timeout is invisible. The same
failure mode is documented at `video_import.py:611`, where the fix was
`asyncio.to_thread`.

These tests measure loop starvation directly: a heartbeat coroutine ticks
alongside the call, and we assert it got to run. See `_count_loop_ticks` for
why tick count rather than elapsed time is the reliable signal.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from app.core.types import TranscriptSegment

# Each simulated S3 round-trip. Sized against this platform's ~15ms asyncio
# timer granularity: at 50ms the cooperative case yielded only ~3 ticks, right
# on the threshold and therefore flaky. 120ms leaves comfortable headroom while
# keeping the suite fast.
_S3_LATENCY_S = 0.12
_HEARTBEAT_INTERVAL_S = 0.005
# A cooperative implementation yields on every threaded round-trip, so the
# heartbeat ticks many times. A blocking one yields never, so it ticks zero
# times. Require a handful to leave room for scheduler variance.
_MIN_TICKS = 3


class _SyncS3Stub:
    """boto3-shaped client whose calls are SYNCHRONOUS, like the real one."""

    def __init__(self, keys: list[str], latency_s: float = _S3_LATENCY_S) -> None:
        self._keys = keys
        self._latency_s = latency_s
        self.list_calls = 0

    def list_objects_v2(self, **_kwargs):
        self.list_calls += 1
        time.sleep(self._latency_s)  # blocking, exactly like botocore
        return {"Contents": [{"Key": k} for k in self._keys]}

    def head_object(self, **_kwargs):
        time.sleep(self._latency_s)
        return {"ContentLength": 1024}


async def _count_loop_ticks(coro):
    """Run *coro*, returning (result, heartbeat ticks that landed during it).

    Tick COUNT, not wall-clock, is the right instrument. Elapsed-time
    thresholds proved unusable here: the platform's asyncio timer granularity
    contributes ~19ms of noise, and the first `asyncio.to_thread` in a process
    pays a one-time ~65ms to spin up a pool worker. Both swamp a millisecond
    budget while saying nothing about the property under test.

    What we actually care about is whether the loop was free to run OTHER work
    during the I/O. A cooperative implementation yields at every await, so the
    heartbeat ticks repeatedly. A blocking one never yields — `with_retry`
    invokes a sync callable inline and its coroutine never reaches a suspension
    point — so the heartbeat gets zero ticks no matter how long the I/O takes.
    That is a clean binary signal, independent of clock resolution.
    """
    ticks = 0
    stop = False

    async def heartbeat():
        nonlocal ticks
        while not stop:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
            ticks += 1

    hb = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)  # let the heartbeat reach its first await
    try:
        result = await coro
    finally:
        stop = True
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
    return result, ticks


def _segments(n: int) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=f"seg_{i:03d}",
            start_ms=i * 10_000,
            end_ms=i * 10_000 + 5_000,
            text="Let me check your range of motion.",
            is_visual_trigger=True,
            trigger_type="active_physical_examination",
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_retrieve_frames_for_triggers_does_not_block_the_loop():
    """The regression: N trigger segments must not stall the loop N x latency."""
    from app.modules.vision import service as vision_service

    stub = _SyncS3Stub([f"frames/sess/{i * 10_000 + 1000}.jpg" for i in range(6)])
    segments = _segments(6)

    with patch.object(vision_service, "get_s3_client", return_value=stub):
        _frames, ticks = await _count_loop_ticks(
            vision_service.retrieve_frames_for_triggers("sess", segments)
        )

    assert ticks >= _MIN_TICKS, (
        f"Event loop ran only {ticks} time(s) during Stage 2 frame retrieval. "
        f"Synchronous boto3 is executing on the loop; while it does, "
        f"approve-stage1's response cannot flush and the ALB 502s (which the "
        f"browser mislabels as a CORS error). Offload via asyncio.to_thread."
    )


@pytest.mark.asyncio
async def test_frame_listing_is_not_repeated_per_segment():
    """One prefix listing, not one per segment.

    Every segment listed the SAME `frames/{session_id}/` prefix, so the
    identical round-trip was repeated once per trigger — wasted work that also
    multiplied the blocking above by the trigger count.
    """
    from app.modules.vision import service as vision_service

    stub = _SyncS3Stub([f"frames/sess/{i * 10_000 + 1000}.jpg" for i in range(6)])

    with patch.object(vision_service, "get_s3_client", return_value=stub):
        await vision_service.retrieve_frames_for_triggers("sess", _segments(6))

    assert stub.list_calls == 1, (
        f"Listed the same prefix {stub.list_calls}x for 6 segments; "
        "hoist the listing out of the per-segment loop."
    )


@pytest.mark.asyncio
async def test_retrieve_all_masked_frames_does_not_block_the_loop():
    """The cadence path (`retrieve_all_masked_frames`) has the same exposure."""
    from app.modules.vision import service as vision_service

    stub = _SyncS3Stub([f"frames/sess/{i * 1000}.jpg" for i in range(4)])

    with patch.object(vision_service, "get_s3_client", return_value=stub):
        _frames, ticks = await _count_loop_ticks(
            vision_service.retrieve_all_masked_frames("sess")
        )

    assert ticks >= _MIN_TICKS, (
        f"Event loop ran only {ticks} time(s) retrieving cadence frames."
    )
