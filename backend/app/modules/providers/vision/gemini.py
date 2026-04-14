"""Gemini vision provider -- real implementation.

Calls Gemini Vision to generate descriptive captions for masked clinical frames.
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
from app.modules.providers.vision.shared import VISION_SYSTEM_PROMPT, build_frame_caption

logger = logging.getLogger("aurion.providers.vision.gemini")

_GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
_MODEL = "gemini-2.5-flash"


class GeminiVisionProvider(VisionProvider):
    """Gemini Vision provider for frame captioning."""

    async def caption_frame(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> FrameCaption:
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")

        image_data = load_frame_image_base64(frame.s3_key)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent",
                    params={"key": _GOOGLE_AI_API_KEY},
                    headers={"Content-Type": "application/json"},
                    json={
                        "systemInstruction": {"parts": [{"text": VISION_SYSTEM_PROMPT}]},
                        "contents": [
                            {
                                "parts": [
                                    {
                                        "inline_data": {
                                            "mime_type": "image/jpeg",
                                            "data": image_data,
                                        }
                                    },
                                    {
                                        "text": (
                                            f"Audio context at this timestamp: \"{anchor.text}\"\n"
                                            f"Describe what is visible in this clinical frame."
                                        ),
                                    },
                                ]
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0.1,
                            "maxOutputTokens": 500,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                content = json.loads(text.strip())
                return build_frame_caption(frame, anchor, content, "gemini")

        except httpx.HTTPError as e:
            logger.error("Gemini vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("gemini", f"Vision captioning failed: {e}", e)
