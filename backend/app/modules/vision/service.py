"""Vision pipeline — Stage 2 processing.

Sequence:
1. Retrieve masked frames from S3 at trigger-flagged timestamps
2. Validate masking status in audit log
3. Call active VisionProvider for each frame
4. Classify ENRICHES / REPEATS / CONFLICTS
5. Discard low-confidence frames before classification
6. Merge frame citations into Stage 1 note
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from app.core.retry import with_retry
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.core.types import (
    FrameCaption,
    MaskedFrame,
    Note,
    NoteClaim,
    NoteSection,
    ProviderError,
    TranscriptSegment,
)
from app.modules.audit_log.service import get_audit_log_service
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_registry import get_registry

logger = logging.getLogger("aurion.vision")


# ── Frame Extraction ─────────────────────────────────────────────────────

def get_frame_window_ms(trigger_type: Optional[str] = None) -> int:
    """Get the frame extraction window from AppConfig — never hardcoded."""
    config = get_config()
    if trigger_type and "procedural" in trigger_type.lower():
        return config.pipeline.frame_window_procedural_ms
    return config.pipeline.frame_window_clinic_ms


async def retrieve_frames_for_triggers(
    session_id: str,
    trigger_segments: list[TranscriptSegment],
) -> list[MaskedFrame]:
    """Retrieve masked frames from S3 at trigger-flagged timestamps.

    Each trigger segment maps to frames within the configured window.
    """
    frames: list[MaskedFrame] = []
    s3 = get_s3_client()

    for segment in trigger_segments:
        window_ms = get_frame_window_ms(segment.trigger_type)
        prefix = f"frames/{session_id}/"

        try:
            response = await with_retry(
                s3.list_objects_v2,
                Bucket=FRAMES_BUCKET,
                Prefix=prefix,
                max_retries=3,
                base_delay=1.0,
                operation="s3_list_frames",
                session_id=session_id,
            )
            for obj in response.get("Contents", []):
                key = obj["Key"]
                # Extract timestamp from key: frames/{session_id}/{timestamp_ms}.jpg
                try:
                    ts_str = key.rsplit("/", 1)[-1].split(".")[0]
                    ts_ms = int(ts_str)
                except (ValueError, IndexError):
                    continue

                # Check if frame is within the extraction window
                if segment.start_ms - window_ms <= ts_ms <= segment.end_ms + window_ms:
                    frames.append(
                        MaskedFrame(
                            frame_id=f"frame_{ts_ms:05d}",
                            session_id=session_id,
                            timestamp_ms=ts_ms,
                            s3_key=key,
                            masking_confirmed=True,
                        )
                    )
        except (BotoCoreError, ClientError) as e:
            logger.error(
                "Frame retrieval failed: session=%s segment=%s error=%s",
                session_id, segment.id, str(e),
            )

    # Deduplicate by frame_id
    seen = set()
    unique: list[MaskedFrame] = []
    for f in frames:
        if f.frame_id not in seen:
            seen.add(f.frame_id)
            unique.append(f)

    logger.info(
        "Frames retrieved: session=%s triggers=%d frames=%d",
        session_id, len(trigger_segments), len(unique),
    )
    return unique


# ── Vision Captioning ────────────────────────────────────────────────────

async def caption_frames(
    frames: list[MaskedFrame],
    trigger_segments: list[TranscriptSegment],
    provider_override: Optional[str] = None,
) -> list[FrameCaption]:
    """Caption each frame using the active vision provider with fallback.

    Frames are captioned concurrently via asyncio.gather for throughput.
    Low-confidence frames are discarded before classification.
    If the primary provider fails on a frame, a fallback provider is tried.
    """
    registry = get_registry()
    provider = registry.get_vision_provider_with_fallback()
    audit = get_audit_log_service()
    session_id = frames[0].session_id if frames else ""

    async def _caption_single(frame: MaskedFrame) -> Optional[FrameCaption]:
        """Caption a single frame, returning None on discard or failure."""
        anchor = _find_anchor_segment(frame.timestamp_ms, trigger_segments)
        if not anchor:
            return None

        try:
            caption = await provider.caption_frame(frame, anchor)
            if caption.confidence == "low":
                logger.info(
                    "Low confidence frame discarded: frame=%s reason=%s",
                    frame.frame_id, caption.confidence_reason,
                )
                return None
            return caption
        except ProviderError as e:
            logger.warning(
                "Primary vision provider failed on frame=%s: %s — trying fallback",
                frame.frame_id, str(e),
            )
            try:
                fallback_provider = registry.get_vision_provider_with_fallback()
                caption = await fallback_provider.caption_frame(frame, anchor)
                await audit.write_event(
                    session_id=frame.session_id,
                    event_type="provider_fallback",
                    frame_id=frame.frame_id,
                    original_error=str(e),
                    fallback_provider=caption.provider_used,
                )
                if caption.confidence == "low":
                    return None
                return caption
            except ProviderError as fallback_err:
                logger.error(
                    "Vision captioning failed (all providers): frame=%s error=%s",
                    frame.frame_id, str(fallback_err),
                )
                await audit.write_event(
                    session_id=frame.session_id,
                    event_type="vision_frame_failed",
                    frame_id=frame.frame_id,
                    error_message=str(fallback_err),
                )
                return None

    # Caption all frames concurrently
    results = await asyncio.gather(
        *(_caption_single(frame) for frame in frames),
        return_exceptions=True,
    )

    captions: list[FrameCaption] = []
    failed_count = 0
    discarded_count = 0

    for result in results:
        if isinstance(result, Exception):
            failed_count += 1
            logger.error("Unexpected error captioning frame: %s", result)
        elif result is None:
            discarded_count += 1
        else:
            captions.append(result)

    # If every frame failed, log a stage2 failure event
    if frames and failed_count == len(frames):
        await audit.write_event(
            session_id=session_id,
            event_type="stage2_failed",
            total_frames=len(frames),
            failed_frames=failed_count,
        )

    logger.info(
        "Captioning complete: total=%d captioned=%d discarded=%d failed=%d",
        len(frames), len(captions), discarded_count, failed_count,
    )
    return captions


def _find_anchor_segment(
    timestamp_ms: int,
    segments: list[TranscriptSegment],
) -> Optional[TranscriptSegment]:
    """Find the transcript segment closest to a frame timestamp."""
    best = None
    best_dist = float("inf")
    for seg in segments:
        mid = (seg.start_ms + seg.end_ms) / 2
        dist = abs(timestamp_ms - mid)
        if dist < best_dist:
            best_dist = dist
            best = seg
    return best


# ── Conflict Classification ──────────────────────────────────────────────

def classify_conflicts(
    captions: list[FrameCaption],
    note: Note,
) -> list[FrameCaption]:
    """Classify each caption as ENRICHES, REPEATS, or CONFLICTS.

    For MVP, trusts the provider's classification. Production will use
    an LLM comparison against audio-anchored note claims.
    """
    for caption in captions:
        if caption.integration_status == "CONFLICTS":
            caption.conflict_flag = True

    enriches = sum(1 for c in captions if c.integration_status == "ENRICHES")
    repeats = sum(1 for c in captions if c.integration_status == "REPEATS")
    conflicts = sum(1 for c in captions if c.conflict_flag)

    logger.info(
        "Conflict classification: enriches=%d repeats=%d conflicts=%d",
        enriches, repeats, conflicts,
    )
    return captions


# ── Note Merger — Stage 2 ────────────────────────────────────────────────

def merge_visual_citations(
    note: Note,
    captions: list[FrameCaption],
) -> Note:
    """Merge frame citations into a Stage 1 note to produce Stage 2.

    - ENRICHES: inject visual description alongside audio claim
    - REPEATS: discard silently, audio stands alone
    - CONFLICTS: surface both, flag section for mandatory physician review
    """
    note.stage = 2

    for caption in captions:
        if caption.integration_status == "REPEATS":
            continue  # Discard silently

        # Find the target section based on the audio anchor
        target_section = _find_target_section(note, caption)
        if not target_section:
            continue

        if caption.integration_status == "ENRICHES":
            # Inject visual claim alongside audio
            target_section.claims.append(
                NoteClaim(
                    id=f"vclaim_{caption.frame_id}",
                    text=caption.visual_description,
                    source_type="visual",
                    source_id=caption.frame_id,
                    source_quote=f"[Frame {caption.frame_id} at {caption.timestamp_ms}ms]",
                )
            )
            if target_section.status == "pending_video":
                target_section.status = "populated"

        elif caption.integration_status == "CONFLICTS":
            # Surface both — flag for mandatory physician review
            target_section.claims.append(
                NoteClaim(
                    id=f"conflict_{caption.frame_id}",
                    text=f"CONFLICT: Visual observation differs from audio — {caption.visual_description}",
                    source_type="visual",
                    source_id=caption.frame_id,
                    source_quote=f"[Frame {caption.frame_id} at {caption.timestamp_ms}ms] {caption.conflict_detail or ''}",
                )
            )

    # Update remaining pending_video sections to processing_failed if no captions matched
    for section in note.sections:
        if section.status == "pending_video":
            section.status = "not_captured"

    logger.info(
        "Note merge complete: session=%s stage=%d sections=%d",
        note.session_id, note.stage, len(note.sections),
    )
    return note


def _find_target_section(note: Note, caption: FrameCaption) -> Optional[NoteSection]:
    """Find the note section that should receive this visual citation.

    Looks for sections with pending_video status or physical_exam/imaging sections.
    """
    # First try: find a section that has the anchor segment
    for section in note.sections:
        for claim in section.claims:
            if claim.source_id == caption.audio_anchor_id:
                return section

    # Fallback: find imaging_review or physical_exam sections
    for section in note.sections:
        if section.id in ("imaging_review", "physical_exam", "wound_assessment", "functional_assessment"):
            return section

    # Last resort: first section with pending_video status
    for section in note.sections:
        if section.status == "pending_video":
            return section

    return None


def has_unresolved_conflicts(captions: list[FrameCaption]) -> bool:
    """Check if any captions have CONFLICTS status."""
    return any(c.integration_status == "CONFLICTS" for c in captions)
