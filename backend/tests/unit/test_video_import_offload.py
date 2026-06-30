"""Unit tests for keeping the video-import pipeline OFF the event loop
(vid-offload-blocking).

The orchestrator ran synchronous boto3 + OpenCV work directly on the API event
loop, blocking concurrent requests (the status poll) long enough for the ALB to
return a gateway 502 — surfaced in the browser as a CORS / ERR_FAILED failure.
These tests pin that the blocking work now runs via ``asyncio.to_thread``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api.v1 import video_import as vi
from app.core.audit_events import AuditEventType
from app.core.types import Transcript, TranscriptSegment

# ── _download_to_path: raw video download runs off the loop (AC-1) ───────────


@pytest.mark.asyncio
async def test_download_offloaded_to_thread() -> None:
    client = SimpleNamespace(download_file=Mock())
    with patch.object(vi.asyncio, "to_thread", AsyncMock()) as to_thread:
        await vi._download_to_path(client, "raw/x.mp4", "/tmp/in.mp4")

    to_thread.assert_awaited_once()
    args = to_thread.await_args.args
    assert args[0] is client.download_file
    assert args[1] == vi.VIDEO_IMPORTS_BUCKET
    assert args[2] == "raw/x.mp4"
    assert args[3] == "/tmp/in.mp4"


# ── _mask_and_store_frame: the blocking mask+store unit (AC-2) ───────────────


def test_mask_and_store_frame_masks_then_stores_on_success() -> None:
    s3 = SimpleNamespace(put_object=Mock())
    result = SimpleNamespace(
        status="success", image_bytes=b"masked", faces_detected=1,
        faces_blurred=1, reason=None,
    )
    sid = uuid.uuid4()
    with patch.object(vi, "mask_frame", return_value=result) as mask:
        out = vi._mask_and_store_frame(s3, sid, 1234, b"raw", True)

    assert out is result
    mask.assert_called_once_with(b"raw", drop_zero_face=True)
    s3.put_object.assert_called_once()
    kwargs = s3.put_object.call_args.kwargs
    assert kwargs["Bucket"] == vi.FRAMES_BUCKET
    assert kwargs["Key"] == f"frames/{sid}/1234.jpg"
    assert kwargs["Body"] == b"masked"


def test_mask_and_store_frame_skips_store_on_drop() -> None:
    """Fail-closed: a non-success mask result never writes to S3."""
    s3 = SimpleNamespace(put_object=Mock())
    result = SimpleNamespace(
        status="dropped", image_bytes=None, faces_detected=0,
        faces_blurred=0, reason="no_face",
    )
    with patch.object(vi, "mask_frame", return_value=result):
        out = vi._mask_and_store_frame(s3, uuid.uuid4(), 1, b"raw", True)

    assert out is result
    s3.put_object.assert_not_called()


# ── _extract_and_mask_frames: the loop offloads per-frame work (AC-2) ────────


@pytest.mark.asyncio
async def test_extract_and_mask_frames_offloads_per_frame() -> None:
    sid = uuid.uuid4()
    transcript = Transcript(
        session_id=str(sid),
        provider_used="t",
        segments=[
            TranscriptSegment(
                id="seg_000", start_ms=0, end_ms=1000, text="exam",
                is_visual_trigger=True, trigger_type="physical_exam",
            )
        ],
    )
    row = SimpleNamespace(transcript_json=transcript.model_dump_json())
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: row)
    )
    masked_result = SimpleNamespace(
        status="success", image_bytes=b"m", faces_detected=1,
        faces_blurred=1, reason=None,
    )
    cfg = SimpleNamespace(
        pipeline=SimpleNamespace(video_import_fps=1),
        feature_flags=SimpleNamespace(video_import_drop_zero_face_frames=True),
    )
    with patch.object(vi, "get_config", return_value=cfg), patch.object(
        vi, "get_frame_window_ms", return_value=0
    ), patch.object(
        vi, "extract_frames_at_windows", AsyncMock(return_value=[(1000, b"jpg")])
    ), patch.object(vi, "get_s3_client", return_value=Mock()), patch.object(
        vi.asyncio, "to_thread", AsyncMock(return_value=masked_result)
    ) as to_thread, patch.object(vi, "write_audit", AsyncMock()) as audit:
        extracted, masked, dropped = await vi._extract_and_mask_frames(
            db, sid, [("/tmp/x.mp4", 0)]
        )

    assert (extracted, masked, dropped) == (1, 1, 0)
    to_thread.assert_awaited_once()
    assert to_thread.await_args.args[0] is vi._mask_and_store_frame
    assert audit.await_args.args[1] == AuditEventType.SERVER_MASKING_APPLIED
