"""Whisper transcription provider — real implementation.

Calls the local Whisper ASR service (onerahmet/openai-whisper-asr-webservice)
or the OpenAI Whisper API depending on configuration.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Optional

import httpx

from app.core.types import ProviderError, Transcript, TranscriptSegment
from app.modules.providers.base import TranscriptionProvider

logger = logging.getLogger("aurion.providers.whisper")

# Local Whisper service URL (docker-compose whisper container)
_WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://localhost:8001")
# OpenAI Whisper API — used if local service unavailable
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_USE_OPENAI_WHISPER = os.getenv("WHISPER_USE_OPENAI", "false").lower() == "true"


class WhisperTranscriptionProvider(TranscriptionProvider):
    """Whisper transcription — local service or OpenAI API."""

    async def transcribe(self, audio: bytes, session_id: str) -> Transcript:
        if _USE_OPENAI_WHISPER and _OPENAI_API_KEY:
            return await self._transcribe_openai(audio, session_id)
        return await self._transcribe_local(audio, session_id)

    async def _transcribe_local(self, audio: bytes, session_id: str) -> Transcript:
        """Call the local Whisper ASR web service."""
        url = f"{_WHISPER_API_URL}/asr"
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    url,
                    params={
                        "encode": "true",
                        "task": "transcribe",
                        "word_timestamps": "true",
                        "output": "json",
                    },
                    files={"audio_file": ("audio.wav", io.BytesIO(audio), "audio/wav")},
                )
                response.raise_for_status()
                data = response.json()
                return self._parse_whisper_response(data, session_id)
        except httpx.HTTPError as e:
            logger.error("Local Whisper call failed: session=%s error=%s", session_id, str(e))
            raise ProviderError("whisper", f"Local Whisper transcription failed: {e}", e)

    async def _transcribe_openai(self, audio: bytes, session_id: str) -> Transcript:
        """Call the OpenAI Whisper API."""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {_OPENAI_API_KEY}"},
                    files={"file": ("audio.wav", io.BytesIO(audio), "audio/wav")},
                    data={
                        "model": "whisper-1",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                    },
                )
                response.raise_for_status()
                data = response.json()
                return self._parse_openai_response(data, session_id)
        except httpx.HTTPError as e:
            logger.error("OpenAI Whisper call failed: session=%s error=%s", session_id, str(e))
            raise ProviderError("whisper", f"OpenAI Whisper transcription failed: {e}", e)

    def _parse_whisper_response(self, data: dict, session_id: str) -> Transcript:
        """Parse response from local Whisper ASR service."""
        segments = []
        raw_segments = data.get("segments", [])

        for i, seg in enumerate(raw_segments):
            start_ms = int(seg.get("start", 0) * 1000)
            end_ms = int(seg.get("end", 0) * 1000)
            text = seg.get("text", "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=f"seg_{i + 1:03d}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )

        logger.info(
            "Whisper local transcription parsed: session=%s segments=%d",
            session_id,
            len(segments),
        )
        return Transcript(
            session_id=session_id,
            provider_used="whisper",
            segments=segments,
        )

    def _parse_openai_response(self, data: dict, session_id: str) -> Transcript:
        """Parse response from OpenAI Whisper API."""
        segments = []
        raw_segments = data.get("segments", [])

        for i, seg in enumerate(raw_segments):
            start_ms = int(seg.get("start", 0) * 1000)
            end_ms = int(seg.get("end", 0) * 1000)
            text = seg.get("text", "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=f"seg_{i + 1:03d}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )

        logger.info(
            "OpenAI Whisper transcription parsed: session=%s segments=%d",
            session_id,
            len(segments),
        )
        return Transcript(
            session_id=session_id,
            provider_used="whisper",
            segments=segments,
        )
