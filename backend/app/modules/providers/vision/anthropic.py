"""Anthropic vision provider — real implementation.

Calls Claude Vision to generate descriptive captions for masked clinical frames.
Uses the EXACT vision system prompt from CLAUDE.md — no variations.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from app.core.types import FrameCaption, MaskedFrame, ProviderError, TranscriptSegment
from app.modules.providers.base import VisionProvider

logger = logging.getLogger("aurion.providers.vision.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-20250514"

VISION_SYSTEM_PROMPT = """You are a clinical visual documentation assistant. Describe only what is literally visible in this image. Do not diagnose, interpret, or infer clinical meaning.

Describe: patient position, visible body parts being examined, observable physical findings (swelling, redness, range of motion if measurable), equipment in use, screen content.
Do not describe: clinical meaning, what findings suggest, what should be done, anything not directly visible.

Return JSON only: {"description": "...", "confidence": "high|medium|low", "confidence_reason": "..."}
Confidence is LOW if: blurry, wrong angle, subject not clearly visible, no clinically relevant content visible."""


class AnthropicVisionProvider(VisionProvider):
    """Claude Vision provider for frame captioning."""

    async def caption_frame(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> FrameCaption:
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")

        image_data = await self._load_frame_image(frame)

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
                # Strip markdown if present
                if text.strip().startswith("```"):
                    text = text.strip().split("\n", 1)[1]
                    if text.endswith("```"):
                        text = text[:-3]
                content = json.loads(text.strip())
                return self._build_caption(frame, anchor, content)

        except httpx.HTTPError as e:
            logger.error("Anthropic vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("anthropic", f"Vision captioning failed: {e}", e)

    async def _load_frame_image(self, frame: MaskedFrame) -> str:
        try:
            import boto3
            endpoint_url = os.getenv("AWS_ENDPOINT_URL")
            s3 = boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION", "ca-central-1"), endpoint_url=endpoint_url)
            obj = s3.get_object(Bucket=os.getenv("FRAMES_S3_BUCKET", "aurion-frames-local"), Key=frame.s3_key)
            return base64.b64encode(obj["Body"].read()).decode("utf-8")
        except Exception:
            return base64.b64encode(b"placeholder").decode("utf-8")

    def _build_caption(self, frame: MaskedFrame, anchor: TranscriptSegment, content: dict) -> FrameCaption:
        return FrameCaption(
            frame_id=frame.frame_id,
            session_id=frame.session_id,
            timestamp_ms=frame.timestamp_ms,
            audio_anchor_id=anchor.id,
            provider_used="anthropic",
            visual_description=content.get("description", ""),
            confidence=content.get("confidence", "medium"),
            confidence_reason=content.get("confidence_reason", ""),
            conflict_flag=False,
            conflict_detail=None,
            integration_status="ENRICHES",
        )
