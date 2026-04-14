"""AssemblyAI transcription provider — real implementation.

Calls the AssemblyAI API for transcription with timestamps.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from app.core.types import ProviderError, Transcript, TranscriptSegment
from app.modules.providers.base import TranscriptionProvider

logger = logging.getLogger("aurion.providers.assemblyai")

_ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
_BASE_URL = "https://api.assemblyai.com/v2"


class AssemblyAITranscriptionProvider(TranscriptionProvider):
    """AssemblyAI transcription provider."""

    async def transcribe(self, audio: bytes, session_id: str) -> Transcript:
        if not _ASSEMBLYAI_API_KEY:
            raise ProviderError("assemblyai", "ASSEMBLYAI_API_KEY not configured")

        headers = {"authorization": _ASSEMBLYAI_API_KEY}

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # Step 1 — upload audio
                upload_resp = await client.post(
                    f"{_BASE_URL}/upload",
                    headers=headers,
                    content=audio,
                )
                upload_resp.raise_for_status()
                upload_url = upload_resp.json()["upload_url"]

                # Step 2 — request transcription
                transcript_resp = await client.post(
                    f"{_BASE_URL}/transcript",
                    headers=headers,
                    json={
                        "audio_url": upload_url,
                        "language_code": "en",
                    },
                )
                transcript_resp.raise_for_status()
                transcript_id = transcript_resp.json()["id"]

                # Step 3 — poll for completion
                while True:
                    poll_resp = await client.get(
                        f"{_BASE_URL}/transcript/{transcript_id}",
                        headers=headers,
                    )
                    poll_resp.raise_for_status()
                    poll_data = poll_resp.json()

                    if poll_data["status"] == "completed":
                        return self._parse_response(poll_data, session_id)
                    elif poll_data["status"] == "error":
                        raise ProviderError(
                            "assemblyai",
                            f"Transcription failed: {poll_data.get('error', 'unknown')}",
                        )

                    # Wait before next poll
                    import asyncio
                    await asyncio.sleep(3)

        except httpx.HTTPError as e:
            logger.error(
                "AssemblyAI call failed: session=%s error=%s", session_id, str(e)
            )
            raise ProviderError("assemblyai", f"AssemblyAI transcription failed: {e}", e)

    def _parse_response(self, data: dict, session_id: str) -> Transcript:
        """Parse AssemblyAI transcript response into standard schema."""
        segments = []
        words = data.get("words", [])

        if not words:
            # Fall back to utterances or sentences
            utterances = data.get("utterances", [])
            for i, utt in enumerate(utterances):
                segments.append(
                    TranscriptSegment(
                        id=f"seg_{i + 1:03d}",
                        start_ms=utt.get("start", 0),
                        end_ms=utt.get("end", 0),
                        text=utt.get("text", "").strip(),
                    )
                )
        else:
            # Group words into sentence-level segments using punctuation
            current_words: list[str] = []
            current_start: Optional[int] = None
            current_end: int = 0
            seg_index = 0

            for word in words:
                if current_start is None:
                    current_start = word.get("start", 0)
                current_end = word.get("end", 0)
                current_words.append(word.get("text", ""))

                # Split on sentence-ending punctuation
                text_so_far = " ".join(current_words)
                if text_so_far.rstrip().endswith((".", "?", "!")):
                    seg_index += 1
                    segments.append(
                        TranscriptSegment(
                            id=f"seg_{seg_index:03d}",
                            start_ms=current_start,
                            end_ms=current_end,
                            text=text_so_far.strip(),
                        )
                    )
                    current_words = []
                    current_start = None

            # Flush remaining words
            if current_words and current_start is not None:
                seg_index += 1
                segments.append(
                    TranscriptSegment(
                        id=f"seg_{seg_index:03d}",
                        start_ms=current_start,
                        end_ms=current_end,
                        text=" ".join(current_words).strip(),
                    )
                )

        logger.info(
            "AssemblyAI transcription parsed: session=%s segments=%d",
            session_id,
            len(segments),
        )
        return Transcript(
            session_id=session_id,
            provider_used="assemblyai",
            segments=segments,
        )
