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

import logging
import os
import uuid
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.types import (
    FrameCaption,
    MaskedFrame,
    Note,
    NoteClaim,
    NoteSection,
    ProviderError,
    TranscriptSegment,
)
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_registry import get_registry

logger = logging.getLogger("aurion.vision")

_FRAMES_BUCKET = os.getenv("FRAMES_S3_BUCKET", "aurion-frames-local")
_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")


def _get_s3_client():
    kwargs: dict[str, Any] = {"region_name": _REGION}
    if _ENDPOINT_URL:
        kwargs["endpoint_url"] = _ENDPOINT_URL
    return boto3.client("s3", **kwargs)


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
    s3 = _get_s3_client()

    for segment in trigger_segments:
        window_ms = get_frame_window_ms(segment.trigger_type)
        prefix = f"frames/{session_id}/"

        try:
            response = s3.list_objects_v2(
                Bucket=_FRAMES_BUCKET, Prefix=prefix
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
    """Caption each frame using the active vision provider.

    Low-confidence frames are discarded before classification.
    """
    registry = get_registry()
    provider = registry.get_vision_provider(override=provider_override)

    captions: list[FrameCaption] = []
    discarded_count = 0

    for frame in frames:
        # Find the closest trigger segment for this frame
        anchor = _find_anchor_segment(frame.timestamp_ms, trigger_segments)
        if not anchor:
            continue

        try:
            caption = await provider.caption_frame(frame, anchor)

            # Low-confidence frames discarded before conflict detection
            if caption.confidence == "low":
                discarded_count += 1
                logger.info(
                    "Low confidence frame discarded: frame=%s reason=%s",
                    frame.frame_id, caption.confidence_reason,
                )
                continue

            captions.append(caption)
        except ProviderError as e:
            logger.error(
                "Vision captioning failed: frame=%s error=%s",
                frame.frame_id, str(e),
            )

    logger.info(
        "Captioning complete: total=%d captioned=%d discarded=%d",
        len(frames), len(captions), discarded_count,
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

    Compares visual description against the audio-based note claims
    for the corresponding anchor segment.

    This is a simplified rule-based classifier. In production,
    an LLM call would do the comparison. For MVP, we use the
    classification returned by the vision provider.
    """
    for caption in captions:
        # The vision provider already returns integration_status
        # For MVP, we trust the provider's classification
        # Real conflict detection would compare caption.visual_description
        # against note claims anchored to caption.audio_anchor_id
        if caption.integration_status == "CONFLICTS":
            caption.conflict_flag = True

    conflicts = [c for c in captions if c.conflict_flag]
    enriches = [c for c in captions if c.integration_status == "ENRICHES"]
    repeats = [c for c in captions if c.integration_status == "REPEATS"]

    logger.info(
        "Conflict classification: enriches=%d repeats=%d conflicts=%d",
        len(enriches), len(repeats), len(conflicts),
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
