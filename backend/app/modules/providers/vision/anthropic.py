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
from app.core.types import FrameCaption, MaskedFrame, ProviderError, TranscriptSegment
from app.modules.providers.base import VisionProvider
from app.modules.providers.note_gen.shared import strip_markdown_fences
from app.modules.providers.vision.shared import VISION_SYSTEM_PROMPT, build_frame_caption

logger = logging.getLogger("aurion.providers.vision.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-20250514"


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
                        "max_tokens": 500,
                        "temperature": 0.1,
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
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["content"][0]["text"]
                content = json.loads(strip_markdown_fences(text))
                return build_frame_caption(frame, anchor, content, "anthropic")

        except httpx.HTTPError as e:
            logger.error("Anthropic vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("anthropic", f"Vision captioning failed: {e}", e)
