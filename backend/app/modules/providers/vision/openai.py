"""OpenAI vision provider -- real implementation.

Calls GPT-4o Vision to generate descriptive captions for masked
clinical frames. For clips, falls back to extracting a midpoint still
via the shared `extract_midpoint_still` helper and routes through the
existing frame path -- DRY (section 6c): zero duplicate request logic.
Uses the shared system prompt and caption builder from shared.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

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
from app.modules.providers.vision._clip_to_still import extract_midpoint_still
from app.modules.providers.vision.shared import (
    VISION_SYSTEM_PROMPT,
    build_frame_caption,
    parse_caption_json,
)

logger = logging.getLogger("aurion.providers.vision.openai")

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_MODEL = "gpt-4o"

# Truncated S3 key length used in log lines so we never leak a full S3
# path (which could carry session-id segments traceable to a patient).
_LOG_KEY_PREFIX_LEN: Final[int] = 12


class OpenAIVisionProvider(VisionProvider):
    """GPT-4o Vision provider for frame captioning."""

    async def caption_frame(
        self,
        frame: MaskedFrame,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        if not _OPENAI_API_KEY:
            raise ProviderError("openai", "OPENAI_API_KEY not configured")

        image_data = load_frame_image_base64(frame.s3_key)
        # AI-PROMPTS-B — assembled prompt or base constant.
        effective_system = system_prompt or VISION_SYSTEM_PROMPT

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": effective_system},
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
                        # AppConfig vision params — admin-tunable at runtime.
                        "temperature": get_config().model_params.vision.temperature,
                        "max_tokens": get_config().model_params.vision.max_tokens,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                # Guard the envelope extraction: a malformed envelope
                # (missing/empty "choices", missing "message"/"content")
                # would otherwise raise KeyError/IndexError/TypeError,
                # escaping `except httpx.HTTPError` and breaking the
                # registry's fallback chain (which only catches
                # ProviderError). Chain the original for debugging.
                try:
                    raw_content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    raise ProviderError(
                        "openai", f"Vision captioning failed: malformed response envelope: {e}", e
                    ) from e
                content = parse_caption_json("openai", raw_content)
                return build_frame_caption(frame, anchor, content, "openai")

        except httpx.HTTPError as e:
            logger.error("OpenAI vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("openai", f"Vision captioning failed: {e}", e)

    async def caption_clip(
        self,
        clip: MaskedClip,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        """Caption a video clip via the lossy midpoint-still fallback.

        GPT-4o doesn't accept MP4 bodies natively, so we:
        1. Pull the clip MP4 from S3 + extract its midpoint frame as a
           JPEG (delegated to the shared `extract_midpoint_still` helper
           -- DRY: one ffmpeg invocation site for the whole codebase).
        2. Route the synthetic `MaskedFrame` through the existing
           `caption_frame` path -- no duplicated GPT-4o request logic.
        3. Flip `evidence_kind="clip"`, `duration_ms=clip.duration_ms`,
           and `degraded_to_frame=True` on the returned caption via
           `model_copy(update=...)`. The reviewer surfaces the "still
           extracted from clip" badge from that flag.

        ``system_prompt`` (AI-PROMPTS-B) flows through to the inner
        ``caption_frame`` call — the synthetic frame uses the same
        physician-customised prompt the clip path would have.

        Provider errors from the inner `caption_frame` call (e.g. a 5xx
        from OpenAI) propagate as-is so the registry's fallback chain
        can trip to the next provider.
        """
        synthetic_frame = await extract_midpoint_still(clip)
        logger.info(
            "openai degraded clip %s to midpoint still",
            clip.s3_key[:_LOG_KEY_PREFIX_LEN],
        )
        # Reuse the existing GPT-4o path. The inner call may raise
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
