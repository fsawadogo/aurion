"""Anthropic vision provider -- real implementation.

Calls Claude Vision to generate descriptive captions for masked clinical frames.
Uses the shared system prompt and caption builder from shared.py.
"""

from __future__ import annotations

import json
import logging
import os

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
from app.modules.providers.vision.shared import (
    VISION_RESPONSE_SCHEMA,
    VISION_SYSTEM_PROMPT,
    build_frame_caption,
)

logger = logging.getLogger("aurion.providers.vision.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"


class AnthropicVisionProvider(VisionProvider):
    """Claude Vision provider for frame captioning."""

    async def caption_frame(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> FrameCaption:
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")

        image_data = load_frame_image_base64(frame.s3_key)

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
                        "system": VISION_SYSTEM_PROMPT,
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
                    # for resilience to API shape changes.
                    for block in data.get("content", []):
                        if "text" in block:
                            content = json.loads(strip_markdown_fences(block["text"]))
                            break
                if content is None:
                    raise ProviderError("anthropic", "No tool_use or text in vision response")
                return build_frame_caption(frame, anchor, content, "anthropic")

        except httpx.HTTPError as e:
            logger.error("Anthropic vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("anthropic", f"Vision captioning failed: {e}", e)

    async def caption_clip(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> FrameCaption:
        """Caption a video clip.

        Stub for P1-1 — the real implementation lands in P1-2 and falls
        back to extracting a midpoint still via ffmpeg, then calls
        `caption_frame`. The resulting citation is tagged
        `degraded_to_frame=true` so the physician sees they're not
        getting full motion fidelity on that citation. See
        docs/plans/p1-1-clip-evidence-schema.md.
        """
        raise NotImplementedError("clip captioning lands in P1-2")
