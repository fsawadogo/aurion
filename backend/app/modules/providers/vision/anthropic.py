"""Anthropic vision provider -- real implementation.

Calls Claude Vision to generate descriptive captions for masked
clinical frames. For clips, falls back to extracting a midpoint still
via the shared `extract_midpoint_still` helper and routes through the
existing frame path -- DRY (section 6c): zero duplicate request logic.
Uses the shared system prompt and caption builder from shared.py.
"""

from __future__ import annotations

import logging
import os
from typing import Final

import httpx

from app.core.s3 import load_frame_image_base64
from app.core.types import (
    FrameCaption,
    MaskedClip,
    MaskedFrame,
    ProviderError,
    TranscriptSegment,
)
from app.modules.config.appconfig_client import get_config
from app.modules.providers.base import VisionProvider
from app.modules.providers.note_gen.shared import strip_markdown_fences
from app.modules.providers.vision._clip_to_still import extract_midpoint_still
from app.modules.providers.vision.shared import (
    VISION_RESPONSE_SCHEMA,
    VISION_SYSTEM_PROMPT,
    build_frame_caption,
    parse_caption_json,
)

logger = logging.getLogger("aurion.providers.vision.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"

# Truncated S3 key length used in log lines so we never leak a full S3
# path (which could carry session-id segments traceable to a patient).
_LOG_KEY_PREFIX_LEN: Final[int] = 12


class AnthropicVisionProvider(VisionProvider):
    """Claude Vision provider for frame captioning."""

    async def caption_frame(
        self,
        frame: MaskedFrame,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")

        image_data = load_frame_image_base64(frame.s3_key)
        # AI-PROMPTS-B — assembled prompt or base constant.
        effective_system = system_prompt or VISION_SYSTEM_PROMPT

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": _ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        # AppConfig vision params — admin-tunable at runtime.
                        "max_tokens": get_config().model_params.vision.max_tokens,
                        "temperature": get_config().model_params.vision.temperature,
                        "system": effective_system,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/jpeg",
                                            "data": image_data,
                                        },
                                    },
                                    {
                                        "type": "text",
                                        "text": (
                                            f"Audio context at this timestamp: \"{anchor.text}\"\n"
                                            f"Describe what is visible in this clinical frame."
                                        ),
                                    },
                                ],
                            }
                        ],
                        # Force the visual description through a schema-
                        # validated tool call so we can't get malformed
                        # JSON back. See vision/shared.py for the schema.
                        "tools": [
                            {
                                "name": "emit_frame_caption",
                                "description": (
                                    "Emit a literal visual description of "
                                    "the frame per the descriptive-only "
                                    "rules in the system prompt."
                                ),
                                "input_schema": VISION_RESPONSE_SCHEMA,
                            }
                        ],
                        "tool_choice": {
                            "type": "tool",
                            "name": "emit_frame_caption",
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                # Tool-use response: pull the structured input directly.
                # Fallback to text block if a future API change drops tool_use.
                content = None
                for block in data.get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "emit_frame_caption":
                        content = block["input"]
                        break
                if content is None:
                    # Defensive fallback — accept any text-bearing block
                    # for resilience to API shape changes. Use the
                    # shared `parse_caption_json` so a malformed text
                    # block raises ProviderError (uniform LSP error
                    # semantic with the other providers + the registry
                    # fallback chain).
                    for block in data.get("content", []):
                        if "text" in block:
                            content = parse_caption_json(
                                "anthropic", strip_markdown_fences(block["text"])
                            )
                            break
                if content is None:
                    raise ProviderError("anthropic", "No tool_use or text in vision response")
                return build_frame_caption(frame, anchor, content, "anthropic")

        except httpx.HTTPError as e:
            logger.error("Anthropic vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("anthropic", f"Vision captioning failed: {e}", e)

    async def caption_clip(
        self,
        clip: MaskedClip,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        """Caption a video clip via the lossy midpoint-still fallback.

        Claude Sonnet 4.6 doesn't accept MP4 bodies natively, so we:
        1. Pull the clip MP4 from S3 + extract its midpoint frame as a
           JPEG (delegated to the shared `extract_midpoint_still` helper
           -- DRY: one ffmpeg invocation site for the whole codebase,
           shared with the OpenAI fallback path).
        2. Route the synthetic `MaskedFrame` through the existing
           `caption_frame` path -- no duplicated Claude request logic.
        3. Flip `evidence_kind="clip"`, `duration_ms=clip.duration_ms`,
           and `degraded_to_frame=True` on the returned caption via
           `model_copy(update=...)`. The reviewer surfaces the "still
           extracted from clip" badge from that flag.

        ``system_prompt`` (AI-PROMPTS-B) flows through to the inner
        ``caption_frame`` call.

        Provider errors from the inner `caption_frame` call (e.g. a 5xx
        from Anthropic) propagate as-is so the registry's fallback chain
        can trip to the next provider.
        """
        synthetic_frame = await extract_midpoint_still(clip)
        logger.info(
            "anthropic degraded clip %s to midpoint still",
            clip.s3_key[:_LOG_KEY_PREFIX_LEN],
        )
        # Reuse the existing Claude path. The inner call may raise
        # ProviderError on 5xx; we let it propagate so the registry's
        # fallback chain can trip.
        caption = await self.caption_frame(
            synthetic_frame, anchor, system_prompt=system_prompt
        )
        return caption.model_copy(
            update={
                "evidence_kind": "clip",
                "duration_ms": clip.duration_ms,
                "degraded_to_frame": True,
            }
        )
