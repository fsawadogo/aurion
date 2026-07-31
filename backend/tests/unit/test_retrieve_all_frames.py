"""retrieve_all_masked_frames — cadence frames must be reachable.

Frame extraction stores frames at trigger windows AND (post-cadence) at cadence
points. The retrieval side was trigger-gated (``retrieve_frames_for_triggers``
loops over trigger segments), so a SILENT exam with zero triggers had frames in
S3 that retrieval could never return — the lab reported "no media" and the note
stayed audio-only. This locks the all-frames retriever: it returns every stored
frame regardless of triggers, keyed off the S3 prefix, sorted by timestamp.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.vision.service as svc


def _obj(ts_ms: int) -> dict:
    return {"Key": f"frames/sess/{ts_ms}.jpg"}


@pytest.mark.asyncio
async def test_returns_all_frames_ignoring_triggers() -> None:
    listing = {"Contents": [_obj(5000), _obj(10000), _obj(15000)]}
    with (
        patch.object(svc, "get_s3_client", return_value=MagicMock()),
        patch.object(svc, "with_retry", AsyncMock(return_value=listing)),
    ):
        frames = await svc.retrieve_all_masked_frames("sess")
    assert [f.timestamp_ms for f in frames] == [5000, 10000, 15000]
    assert all(f.masking_confirmed for f in frames)
    assert frames[0].frame_id == "frame_05000"


@pytest.mark.asyncio
async def test_sorted_by_timestamp_and_deduped() -> None:
    listing = {"Contents": [_obj(15000), _obj(5000), _obj(5000), _obj(10000)]}
    with (
        patch.object(svc, "get_s3_client", return_value=MagicMock()),
        patch.object(svc, "with_retry", AsyncMock(return_value=listing)),
    ):
        frames = await svc.retrieve_all_masked_frames("sess")
    assert [f.timestamp_ms for f in frames] == [5000, 10000, 15000]  # sorted + deduped


@pytest.mark.asyncio
async def test_empty_prefix_returns_empty() -> None:
    with (
        patch.object(svc, "get_s3_client", return_value=MagicMock()),
        patch.object(svc, "with_retry", AsyncMock(return_value={"Contents": []})),
    ):
        frames = await svc.retrieve_all_masked_frames("sess")
    assert frames == []


@pytest.mark.asyncio
async def test_malformed_key_is_skipped_not_fatal() -> None:
    listing = {"Contents": [_obj(5000), {"Key": "frames/sess/notanumber.jpg"}]}
    with (
        patch.object(svc, "get_s3_client", return_value=MagicMock()),
        patch.object(svc, "with_retry", AsyncMock(return_value=listing)),
    ):
        frames = await svc.retrieve_all_masked_frames("sess")
    assert [f.timestamp_ms for f in frames] == [5000]
