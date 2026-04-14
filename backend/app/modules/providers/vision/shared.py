"""Shared logic for vision providers.

All three vision providers (OpenAI, Anthropic, Gemini) use the same system
prompt and build FrameCaption objects the same way.  Provider-specific code
is limited to the HTTP call and response extraction.
"""

from __future__ import annotations

from app.core.types import FrameCaption, MaskedFrame, TranscriptSegment

# EXACT vision system prompt from CLAUDE.md -- no variations.
# Shared across all vision providers.
VISION_SYSTEM_PROMPT = """You are a clinical visual documentation assistant. Describe only what is literally visible in this image. Do not diagnose, interpret, or infer clinical meaning.

Describe: patient position, visible body parts being examined, observable physical findings (swelling, redness, range of motion if measurable), equipment in use, screen content.
Do not describe: clinical meaning, what findings suggest, what should be done, anything not directly visible.

Return JSON only: {"description": "...", "confidence": "high|medium|low", "confidence_reason": "..."}
Confidence is LOW if: blurry, wrong angle, subject not clearly visible, no clinically relevant content visible."""


def build_frame_caption(
    frame: MaskedFrame,
    anchor: TranscriptSegment,
    content: dict,
    provider_name: str,
) -> FrameCaption:
    """Build a FrameCaption from the parsed LLM response.

    All vision providers return the same caption structure -- only the
    ``provider_used`` field differs.
    """
    return FrameCaption(
        frame_id=frame.frame_id,
        session_id=frame.session_id,
        timestamp_ms=frame.timestamp_ms,
        audio_anchor_id=anchor.id,
        provider_used=provider_name,
        visual_description=content.get("description", ""),
        confidence=content.get("confidence", "medium"),
        confidence_reason=content.get("confidence_reason", ""),
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
    )
