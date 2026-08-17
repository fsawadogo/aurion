"""Fail-closed motion-clip generation for recorded encounter imports."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.audit_events import AuditEventType
from app.core.s3 import FRAMES_BUCKET
from app.core.types import TranscriptSegment
from app.modules.video_import.extraction import (
    encode_jpeg_frames_to_h264,
    extract_frames_at_windows,
)
from app.modules.video_import.masking import mask_frame

logger = logging.getLogger("aurion.video_import.clips")

AuditWriter = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class ImportClipWindow:
    """One trigger-centred window routed to its owning uploaded video."""

    video_path: str
    local_start_ms: int
    local_end_ms: int
    anchor_ms: int
    trigger_segment_id: str


def _evenly_sample_segments(
    segments: list[TranscriptSegment],
    count: int,
) -> list[TranscriptSegment]:
    if count <= 0:
        return []
    if count >= len(segments):
        return segments
    if count == 1:
        return [segments[len(segments) // 2]]
    last = len(segments) - 1
    return [segments[round(slot * last / (count - 1))] for slot in range(count)]


def select_import_clip_windows(
    trigger_segments: list[TranscriptSegment],
    source_clips: list[tuple[str, int]],
    *,
    total_duration_ms: int,
    clip_window_ms: int,
    max_clips: int,
) -> list[ImportClipWindow]:
    """Build bounded, non-redundant motion windows around spoken triggers.

    Nearby trigger segments are clustered into one configured-length clip.
    This is specialty-agnostic: the existing trigger classifier decides what
    is clinically visual, while this function only preserves motion around
    those timestamps. Candidates are sampled across the full visit when they
    exceed the existing Stage-2 evidence budget.
    """
    if (
        not trigger_segments
        or not source_clips
        or clip_window_ms <= 0
        or max_clips <= 0
    ):
        return []

    ordered_triggers = sorted(
        trigger_segments,
        key=lambda segment: (segment.start_ms + segment.end_ms) // 2,
    )
    clusters: list[list[TranscriptSegment]] = []
    for segment in ordered_triggers:
        center = (segment.start_ms + segment.end_ms) // 2
        if not clusters:
            clusters.append([segment])
            continue
        cluster_start = (
            clusters[-1][0].start_ms + clusters[-1][0].end_ms
        ) // 2
        if center - cluster_start < clip_window_ms:
            clusters[-1].append(segment)
        else:
            clusters.append([segment])

    representatives = [cluster[len(cluster) // 2] for cluster in clusters]
    representatives = _evenly_sample_segments(representatives, max_clips)

    sorted_clips = sorted(source_clips, key=lambda item: item[1])
    selected: list[ImportClipWindow] = []
    for segment in representatives:
        anchor_ms = max((segment.start_ms + segment.end_ms) // 2, 0)
        owner = 0
        for index, (_, offset_ms) in enumerate(sorted_clips):
            if offset_ms <= anchor_ms:
                owner = index
            else:
                break

        video_path, offset_ms = sorted_clips[owner]
        next_offset_ms = (
            sorted_clips[owner + 1][1]
            if owner + 1 < len(sorted_clips)
            else total_duration_ms
        )
        source_duration_ms = max(next_offset_ms - offset_ms, 0)
        if source_duration_ms <= 0:
            continue

        local_anchor_ms = min(max(anchor_ms - offset_ms, 0), source_duration_ms)
        half_window_ms = clip_window_ms // 2
        local_start_ms = max(local_anchor_ms - half_window_ms, 0)
        local_end_ms = min(local_start_ms + clip_window_ms, source_duration_ms)
        # Preserve the configured duration near the end of a source clip when
        # possible by shifting the start backward after the end clamp.
        local_start_ms = max(local_end_ms - clip_window_ms, 0)
        if local_end_ms <= local_start_ms:
            continue
        selected.append(
            ImportClipWindow(
                video_path=video_path,
                local_start_ms=local_start_ms,
                local_end_ms=local_end_ms,
                anchor_ms=anchor_ms,
                trigger_segment_id=segment.id,
            )
        )
    return selected


async def generate_masked_trigger_clips(
    *,
    session_id: uuid.UUID,
    trigger_segments: list[TranscriptSegment],
    source_clips: list[tuple[str, int]],
    total_duration_ms: int,
    clip_window_ms: int,
    max_clips: int,
    fps: int,
    preprocessing_concurrency: int,
    drop_zero_face: bool,
    redact_faceless: bool,
    s3: Any,
    audit_writer: AuditWriter,
) -> tuple[int, int, int]:
    """Create silent masked H.264 clips from recorded encounter video.

    Every encoded frame passes through fail-closed face/text masking. If any
    sampled frame fails masking, the entire candidate clip is dropped and no
    bytes are stored. Failures stay local to a clip so audio and still-frame
    enrichment remain available.

    Returns ``(clips_attempted, clips_stored, clips_dropped)``.
    """
    windows = select_import_clip_windows(
        trigger_segments,
        source_clips,
        total_duration_ms=total_duration_ms,
        clip_window_ms=clip_window_ms,
        max_clips=max_clips,
    )
    if not windows:
        return (0, 0, 0)

    stored = 0
    dropped = 0
    # Deliberately serial: OpenCV's native detectors have previously exceeded
    # the ECS memory budget when several masks ran concurrently.
    for window in windows:
        frames = await extract_frames_at_windows(
            window.video_path,
            [(window.local_start_ms, window.local_end_ms)],
            fps,
            max_concurrency=preprocessing_concurrency,
        )
        masked_frames: list[bytes] = []
        frames_with_faces = 0
        faces_blurred = 0
        masking_failed = len(frames) < 2
        for _, jpg_bytes in frames:
            result = await asyncio.to_thread(
                mask_frame,
                jpg_bytes,
                drop_zero_face=drop_zero_face,
                redact_faceless=redact_faceless,
            )
            if result.status != "success" or result.image_bytes is None:
                masking_failed = True
                break
            masked_frames.append(result.image_bytes)
            if result.faces_detected > 0:
                frames_with_faces += 1
            faces_blurred += result.faces_blurred

        if masking_failed:
            await audit_writer(
                session_id,
                AuditEventType.CLIP_DROPPED,
                reason="masking_failed",
                origin="server",
                timestamp_ms=window.anchor_ms,
            )
            dropped += 1
            continue

        try:
            body = await encode_jpeg_frames_to_h264(masked_frames, fps=fps)
            clip_id = uuid.uuid4().hex
            key = f"clips/{session_id}/{window.anchor_ms:09d}_{clip_id}.mp4"
            await asyncio.to_thread(
                s3.put_object,
                Bucket=FRAMES_BUCKET,
                Key=key,
                Body=body,
                ContentType="video/mp4",
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:  # noqa: BLE001 - clip path degrades to stills
            logger.warning(
                "Masked import clip dropped: session=%s error_type=%s",
                str(session_id)[:8],
                type(exc).__name__,
            )
            await audit_writer(
                session_id,
                AuditEventType.CLIP_DROPPED,
                reason="upload_failed",
                origin="server",
                timestamp_ms=window.anchor_ms,
            )
            dropped += 1
            continue

        duration_ms = round(len(masked_frames) * 1000 / max(fps, 1))
        await audit_writer(
            session_id,
            AuditEventType.CLIP_UPLOADED,
            timestamp_ms=window.anchor_ms,
            bytes=len(body),
            duration_ms=duration_ms,
            trigger_segment_id=window.trigger_segment_id,
            masking_status="success",
            frames_total=len(masked_frames),
            frames_with_faces=frames_with_faces,
            faces_blurred=faces_blurred,
            source="trigger",
        )
        stored += 1

    logger.info(
        "Video-import trigger clips: session=%s attempted=%d stored=%d dropped=%d",
        str(session_id)[:8],
        len(windows),
        stored,
        dropped,
    )
    return (len(windows), stored, dropped)
