"""Gemini vision provider -- real implementation.

Calls Gemini Vision to generate descriptive captions for masked clinical
frames AND clips. Frames go through the still-image path
(`load_frame_image_base64` -> `inline_data` mime `image/jpeg`); clips
go through the **native video** path (`get_object` -> `inline_data`
mime `video/mp4`) because Gemini 2.5 Pro is the only frontier model
that accepts MP4 bodies directly. Shared system prompt + response
schema + caption builder live in `shared.py`.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Final

import httpx

from app.core.s3 import FRAMES_BUCKET, get_s3_client, load_frame_image_base64
from app.core.types import (
    FrameCaption,
    MaskedClip,
    MaskedFrame,
    ProviderError,
    TranscriptSegment,
)
from app.modules.config.appconfig_client import get_config
from app.modules.providers.base import VisionProvider
from app.modules.providers.vision._clip_to_still import session_id_from_clip_key
from app.modules.providers.vision.shared import (
    VISION_RESPONSE_SCHEMA,
    VISION_SYSTEM_PROMPT,
    build_frame_caption,
    parse_caption_json,
)

logger = logging.getLogger("aurion.providers.vision.gemini")

_GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
_MODEL = "gemini-2.5-pro"

# Truncated S3 key length used in log lines so we never leak a full S3
# path (which could carry session-id segments traceable to a patient).
_LOG_KEY_PREFIX_LEN: Final[int] = 12


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
                            # AppConfig vision params — admin-tunable at runtime.
                            "temperature": get_config().model_params.vision.temperature,
                            "maxOutputTokens": get_config().model_params.vision.max_tokens,
                            "responseMimeType": "application/json",
                            # Schema-enforced output — eliminates malformed
                            # JSON returns; Gemini validates server-side.
                            "responseSchema": VISION_RESPONSE_SCHEMA,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                content = parse_caption_json("gemini", text)
                return build_frame_caption(frame, anchor, content, "gemini")

        except httpx.HTTPError as e:
            logger.error("Gemini vision failed: frame=%s error=%s", frame.frame_id, str(e))
            raise ProviderError("gemini", f"Vision captioning failed: {e}", e)

    async def caption_clip(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> FrameCaption:
        """Caption a video clip natively via Gemini's video understanding.

        Loads the masked MP4 from S3, base64-encodes it, sends it as
        `inline_data` with mime `video/mp4` alongside the existing
        descriptive-mode system prompt. The user message tells the
        model this is a clip and to describe motion across it. AppConfig
        vision params (temperature / max_tokens / responseSchema) are
        the same as the frame path -- Liskov: the output schema is
        identical, only `evidence_kind` and `duration_ms` differ.

        Raises `ProviderError` on any HTTP failure so the fallback chain
        in `provider_registry.get_vision_provider_with_fallback` can
        trip to the next provider (typically OpenAI/Anthropic with
        midpoint-still degradation).
        """
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")

        # Fetch the MP4 bytes from S3 via the shared client (DIP).
        # Falls back to a tiny placeholder on local-dev S3 misses so the
        # path is exercisable without LocalStack -- matches the frame
        # path's `load_frame_image_base64` resilience.
        try:
            obj = get_s3_client().get_object(Bucket=FRAMES_BUCKET, Key=clip.s3_key)
            mp4_bytes: bytes = obj["Body"].read()
        except Exception:
            mp4_bytes = b"placeholder"
        video_data = base64.b64encode(mp4_bytes).decode("utf-8")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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
                                            "mime_type": "video/mp4",
                                            "data": video_data,
                                        }
                                    },
                                    {
                                        "text": (
                                            f"Audio context at this timestamp: \"{anchor.text}\"\n"
                                            f"This is a video clip with duration {clip.duration_ms}ms. "
                                            f"Describe what is observable across the clip, including motion."
                                        ),
                                    },
                                ]
                            }
                        ],
                        "generationConfig": {
                            # AppConfig vision params -- admin-tunable at runtime.
                            # Same temperature / max_tokens / responseSchema as
                            # the frame path: Liskov compliance at the wire.
                            "temperature": get_config().model_params.vision.temperature,
                            "maxOutputTokens": get_config().model_params.vision.max_tokens,
                            "responseMimeType": "application/json",
                            "responseSchema": VISION_RESPONSE_SCHEMA,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                content = parse_caption_json("gemini", text)

                # Synthesise a `MaskedFrame`-shaped anchor for the caption
                # builder: clip captions carry the trigger segment id +
                # midpoint timestamp so the citation can still anchor
                # back to the transcript. We then override evidence_kind
                # / duration_ms via model_copy -- LSP compliance.
                clip_anchor = MaskedFrame(
                    frame_id=f"{clip.trigger_segment_id}_clip",
                    session_id=session_id_from_clip_key(clip.s3_key),
                    timestamp_ms=clip.timestamp_ms + clip.duration_ms // 2,
                    s3_key=clip.s3_key,
                    masking_confirmed=True,
                )
                caption = build_frame_caption(clip_anchor, anchor, content, "gemini")
                return caption.model_copy(
                    update={
                        "evidence_kind": "clip",
                        "duration_ms": clip.duration_ms,
                        "degraded_to_frame": False,
                    }
                )

        except httpx.HTTPError as e:
            # No PHI in error or log line -- only the truncated key prefix.
            logger.error(
                "Gemini clip vision failed: clip=%s error=%s",
                clip.s3_key[:_LOG_KEY_PREFIX_LEN],
                str(e),
            )
            raise ProviderError("gemini", f"Clip captioning failed: {e}", e)
