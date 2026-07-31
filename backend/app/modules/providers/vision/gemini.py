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

import asyncio
import base64
import logging
import os
import random
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

# Rate-limit / transient-error retry policy. The dev Gemini key throttles hard
# when a Stage-2 run (or the Grounded Lab replay) captions many frames at once:
# a single-shot call turns a 429 into a discarded frame, and a whole session
# into zero findings. Bounded exponential backoff with full jitter lets a burst
# drain instead of collapsing. 429 = rate limit, 503 = transient upstream.
_RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 503})
_MAX_RETRIES: Final[int] = 5
_BACKOFF_BASE_SECONDS: Final[float] = 1.0
_BACKOFF_MAX_SECONDS: Final[float] = 30.0

_GENERATE_CONTENT_URL: Final[str] = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _redact(text: str) -> str:
    """Strip the Google AI API key from any string headed for a log line or a
    raised error.

    httpx embeds the full request URL — including the ``?key=…`` query param —
    in its ``HTTPStatusError`` message, so an un-redacted ``str(e)`` writes the
    live secret to CloudWatch. Redact at every point ``str(e)`` can escape.
    """
    if _GOOGLE_AI_API_KEY:
        return text.replace(_GOOGLE_AI_API_KEY, "***")
    return text


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds form) when present."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


async def _post_generate_content(
    client: httpx.AsyncClient,
    model: str,
    json_body: dict,
    *,
    label: str,
) -> httpx.Response:
    """POST to Gemini ``generateContent`` with bounded backoff on 429/503.

    Retries a rate-limited / transiently-failed call up to ``_MAX_RETRIES``
    times, honouring a ``Retry-After`` header when the server sends one, else
    backing off 1s, 2s, 4s, … with full jitter, capped at
    ``_BACKOFF_MAX_SECONDS``. The API key is never logged (only the status and
    the delay). Once retries are exhausted — or on any non-retryable status —
    the response's ``raise_for_status`` propagates so the existing fallback
    chain still engages.
    """
    url = _GENERATE_CONTENT_URL.format(model=model)
    attempt = 0
    while True:
        response = await client.post(
            url,
            params={"key": _GOOGLE_AI_API_KEY},
            headers={"Content-Type": "application/json"},
            json=json_body,
        )
        if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            delay = _retry_after_seconds(response)
            if delay is None:
                backoff = min(
                    _BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_MAX_SECONDS
                )
                delay = random.uniform(0.0, backoff)
            logger.warning(
                "Gemini %s rate-limited (HTTP %d); retry %d/%d in %.1fs",
                label,
                response.status_code,
                attempt + 1,
                _MAX_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue
        response.raise_for_status()
        return response


class GeminiVisionProvider(VisionProvider):
    """Gemini Vision provider for frame captioning."""

    async def caption_frame(
        self,
        frame: MaskedFrame,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")

        image_data = load_frame_image_base64(frame.s3_key)
        # AI-PROMPTS-B — assembled prompt or base constant.
        effective_system = system_prompt or VISION_SYSTEM_PROMPT
        # #437 — model id is config-driven (AppConfig override → compiled-in
        # default). Resolved per call so a config flip lands without redeploy.
        model = get_config().model_versions.gemini or _MODEL

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await _post_generate_content(
                    client,
                    model,
                    {
                        "systemInstruction": {"parts": [{"text": effective_system}]},
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
                    label="frame vision",
                )
                data = response.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError) as e:
                    raise ProviderError(
                        "gemini", f"Vision captioning failed: malformed response envelope: {e}", e
                    ) from e
                content = parse_caption_json("gemini", text)
                return build_frame_caption(frame, anchor, content, "gemini")

        except httpx.HTTPError as e:
            redacted = _redact(str(e))
            logger.error("Gemini vision failed: frame=%s error=%s", frame.frame_id, redacted)
            raise ProviderError("gemini", f"Vision captioning failed: {redacted}", e)

    async def caption_clip(
        self,
        clip: MaskedClip,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        """Caption a video clip natively via Gemini's video understanding.

        Loads the masked MP4 from S3, base64-encodes it, sends it as
        `inline_data` with mime `video/mp4` alongside the existing
        descriptive-mode system prompt. The user message tells the
        model this is a clip and to describe motion across it. AppConfig
        vision params (temperature / max_tokens / responseSchema) are
        the same as the frame path -- Liskov: the output schema is
        identical, only `evidence_kind` and `duration_ms` differ.

        ``system_prompt`` (AI-PROMPTS-B) is the service-assembled
        ``vision_clip`` overlay; falls back to ``VISION_SYSTEM_PROMPT``.

        Raises `ProviderError` on any HTTP failure so the fallback chain
        in `provider_registry.get_vision_provider_with_fallback` can
        trip to the next provider (typically OpenAI/Anthropic with
        midpoint-still degradation).
        """
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")
        # AI-PROMPTS-B — assembled prompt or base constant.
        effective_system = system_prompt or VISION_SYSTEM_PROMPT

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

        # Gemini samples inline video at 1 fps by DEFAULT, which would throw
        # away the extra frames a higher capture rate produces. Pin the sampling
        # rate to the configured video-capture fps so a denser clip actually
        # yields finer motion detail (gait / ROM / procedural). Token cost and
        # latency scale ~linearly with fps, so this is bounded by the same
        # AppConfig knob that bounds capture (pipeline.video_capture_fps, 1-10).
        sampling_fps = get_config().pipeline.video_capture_fps
        # #437 — config-driven model id (override → compiled-in default).
        model = get_config().model_versions.gemini or _MODEL

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await _post_generate_content(
                    client,
                    model,
                    {
                        "systemInstruction": {"parts": [{"text": effective_system}]},
                        "contents": [
                            {
                                "parts": [
                                    {
                                        "inline_data": {
                                            "mime_type": "video/mp4",
                                            "data": video_data,
                                        },
                                        # Sample at the capture rate, not the
                                        # 1-fps default (see sampling_fps above).
                                        "video_metadata": {"fps": sampling_fps},
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
                    label="clip vision",
                )
                data = response.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError) as e:
                    raise ProviderError(
                        "gemini", f"Clip captioning failed: malformed response envelope: {e}", e
                    ) from e
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
            # Redact the API key: httpx embeds the ?key=… URL in its error.
            redacted = _redact(str(e))
            logger.error(
                "Gemini clip vision failed: clip=%s error=%s",
                clip.s3_key[:_LOG_KEY_PREFIX_LEN],
                redacted,
            )
            raise ProviderError("gemini", f"Clip captioning failed: {redacted}", e)
