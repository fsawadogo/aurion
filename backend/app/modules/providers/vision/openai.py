"""OpenAI vision provider -- real implementation.

Calls GPT-4o Vision to generate descriptive captions for masked clinical frames.
Uses the shared system prompt and caption builder from shared.py.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from app.core.s3 import load_frame_image_base64
from app.core.types import FrameCaption, MaskedFrame, ProviderError, TranscriptSegment
from app.modules.providers.base import VisionProvider
from app.modules.providers.vision.shared import VISION_SYSTEM_PROMPT, build_frame_caption

logger = logging.getLogger("aurion.providers.vision.openai")

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_MODEL = "gpt-4o"


class OpenAIVisionProvider(VisionProvider):
    """GPT-4o Vision provider for frame captioning."""

    async def caption_frame(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> FrameCaption:
        if not _OPENAI_API_KEY:
            raise ProviderError("openai", "OPENAI_API_KEY not configured")

        image_data = load_frame_image_base64(frame.s3_key)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Audio context at this timestamp: \"{anchor.text}\"\n"
                                    f"Describe what is visible in this clinical frame."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ]

                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "temperature": 0.1,
                        "max_tokens": 500,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = json.loads(data["choices"][0]["message"]["content"])
                return build_frame_caption(frame, anchor, content, "openai")

        except httpx.HTTPError as e:
            logger.error("OpenAI vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("openai", f"Vision captioning failed: {e}", e)
