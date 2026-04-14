"""Gemini note generation provider -- real implementation.

Calls Gemini to generate structured SOAP notes from transcripts.
Uses the shared system prompt and response parser from shared.py.
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from app.core.types import Note, ProviderError, Template, Transcript
from app.modules.providers.base import NoteGenerationProvider
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_SYSTEM_PROMPT,
    build_user_prompt,
    parse_note_response,
)

logger = logging.getLogger("aurion.providers.note_gen.gemini")

_GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
_MODEL = "gemini-2.5-flash"


class GeminiNoteGenerationProvider(NoteGenerationProvider):
    """Gemini note generation provider."""

    async def generate_note(
        self, transcript: Transcript, template: Template, stage: int
    ) -> Note:
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")

        user_prompt = build_user_prompt(transcript, template, stage)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent",
                    params={"key": _GOOGLE_AI_API_KEY},
                    headers={"Content-Type": "application/json"},
                    json={
                        "systemInstruction": {
                            "parts": [{"text": NOTE_GEN_SYSTEM_PROMPT}]
                        },
                        "contents": [
                            {"parts": [{"text": user_prompt}]}
                        ],
                        "generationConfig": {
                            "temperature": 0.1,
                            "maxOutputTokens": 2000,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return parse_note_response(content, transcript, template, stage, "gemini")

        except httpx.HTTPError as e:
            logger.error("Gemini note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("gemini", f"Note generation failed: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Gemini response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("gemini", f"Response parse failed: {e}", e)
