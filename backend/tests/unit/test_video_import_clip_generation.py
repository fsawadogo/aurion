"""Recorded imports produce bounded, fail-closed motion evidence."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit_events import AuditEventType
from app.core.types import TranscriptSegment
from app.modules.video_import import clips as clip_generation
from app.modules.video_import.masking import MaskedFrameResult


def _segment(segment_id: str, center_ms: int) -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        start_ms=center_ms - 100,
        end_ms=center_ms + 100,
        text="performing examination manoeuvre",
        is_visual_trigger=True,
        trigger_type="active_physical_examination",
    )


def test_trigger_clip_windows_cluster_route_and_preserve_visit_coverage() -> None:
    windows = clip_generation.select_import_clip_windows(
        [_segment("seg_1", 1000), _segment("seg_2", 2500), _segment("seg_3", 12_000)],
        [("first.mp4", 0), ("second.mp4", 10_000)],
        total_duration_ms=20_000,
        clip_window_ms=7000,
        max_clips=10,
    )

    assert [(window.video_path, window.trigger_segment_id) for window in windows] == [
        ("first.mp4", "seg_2"),
        ("second.mp4", "seg_3"),
    ]
    assert [(window.local_start_ms, window.local_end_ms) for window in windows] == [
        (0, 7000),
        (0, 7000),
    ]


def test_trigger_clip_windows_use_existing_budget_across_full_timeline() -> None:
    windows = clip_generation.select_import_clip_windows(
        [_segment(f"seg_{index}", index * 10_000 + 1000) for index in range(5)],
        [("visit.mp4", 0)],
        total_duration_ms=50_000,
        clip_window_ms=7000,
        max_clips=2,
    )

    assert [window.anchor_ms for window in windows] == [1000, 41_000]


@pytest.mark.asyncio
async def test_import_clip_masks_every_frame_then_stores_silent_mp4() -> None:
    session_id = uuid.uuid4()
    s3 = MagicMock()
    audit = AsyncMock()
    successes = [
        MaskedFrameResult(
            status="success",
            image_bytes=b"masked-1",
            faces_detected=1,
            faces_blurred=1,
        ),
        MaskedFrameResult(
            status="success",
            image_bytes=b"masked-2",
            faces_detected=0,
            faces_blurred=0,
            text_regions_redacted=1,
        ),
    ]

    with (
        patch.object(
            clip_generation,
            "extract_frames_at_windows",
            AsyncMock(return_value=[(0, b"raw-1"), (1000, b"raw-2")]),
        ),
        patch.object(
            clip_generation,
            "mask_frame",
            MagicMock(side_effect=successes),
        ) as mask,
        patch.object(
            clip_generation,
            "encode_jpeg_frames_to_h264",
            AsyncMock(return_value=b"silent-h264"),
        ) as encode,
    ):
        result = await clip_generation.generate_masked_trigger_clips(
            session_id=session_id,
            trigger_segments=[_segment("seg_exam", 5000)],
            source_clips=[("visit.mp4", 0)],
            total_duration_ms=10_000,
            clip_window_ms=7000,
            max_clips=10,
            fps=1,
            preprocessing_concurrency=2,
            drop_zero_face=True,
            redact_faceless=True,
            s3=s3,
            audit_writer=audit,
        )

    assert result == (1, 1, 0)
    assert mask.call_count == 2
    encode.assert_awaited_once_with([b"masked-1", b"masked-2"], fps=1)
    _, put = s3.put_object.call_args
    assert put["Bucket"] == clip_generation.FRAMES_BUCKET
    assert put["Key"].startswith(f"clips/{session_id}/000005000_")
    assert put["Body"] == b"silent-h264"
    assert put["ContentType"] == "video/mp4"
    assert put["ServerSideEncryption"] == "aws:kms"
    uploaded = audit.await_args
    assert uploaded.args[1] == AuditEventType.CLIP_UPLOADED
    assert uploaded.kwargs["trigger_segment_id"] == "seg_exam"
    assert uploaded.kwargs["frames_total"] == 2
    assert uploaded.kwargs["frames_with_faces"] == 1
    assert uploaded.kwargs["faces_blurred"] == 1


@pytest.mark.asyncio
async def test_one_masking_failure_drops_whole_clip_without_storage() -> None:
    session_id = uuid.uuid4()
    s3 = MagicMock()
    audit = AsyncMock()
    mask_results = [
        MaskedFrameResult(status="success", image_bytes=b"masked-1"),
        MaskedFrameResult(status="failed", reason="detect_error"),
    ]

    with (
        patch.object(
            clip_generation,
            "extract_frames_at_windows",
            AsyncMock(return_value=[(0, b"raw-1"), (1000, b"raw-2")]),
        ),
        patch.object(
            clip_generation,
            "mask_frame",
            MagicMock(side_effect=mask_results),
        ),
        patch.object(
            clip_generation,
            "encode_jpeg_frames_to_h264",
            AsyncMock(),
        ) as encode,
    ):
        result = await clip_generation.generate_masked_trigger_clips(
            session_id=session_id,
            trigger_segments=[_segment("seg_exam", 5000)],
            source_clips=[("visit.mp4", 0)],
            total_duration_ms=10_000,
            clip_window_ms=7000,
            max_clips=10,
            fps=1,
            preprocessing_concurrency=2,
            drop_zero_face=True,
            redact_faceless=True,
            s3=s3,
            audit_writer=audit,
        )

    assert result == (1, 0, 1)
    encode.assert_not_awaited()
    s3.put_object.assert_not_called()
    assert audit.await_args.args[1] == AuditEventType.CLIP_DROPPED
    assert audit.await_args.kwargs == {
        "reason": "masking_failed",
        "origin": "server",
        "timestamp_ms": 5000,
    }
