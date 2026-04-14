"""OpenAI note generation provider -- real implementation.

Calls GPT-4o to generate structured SOAP notes from transcripts.
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

logger = logging.getLogger("aurion.providers.note_gen.openai")

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_MODEL = "gpt-4o"


class OpenAINoteGenerationProvider(NoteGenerationProvider):
    """GPT-4o note generation provider."""

    async def generate_note(
        self, transcript: Transcript, template: Template, stage: int
    ) -> Note:
        if not _OPENAI_API_KEY:
            raise ProviderError("openai", "OPENAI_API_KEY not configured")

        user_prompt = build_user_prompt(transcript, template, stage)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "temperature": 0.1,
                        "max_tokens": 2000,
                        "messages": [
                            {"role": "system", "content": NOTE_GEN_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return parse_note_response(content, transcript, template, stage, "openai")

        except httpx.HTTPError as e:
            logger.error("OpenAI note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("openai", f"Note generation failed: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("OpenAI response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("openai", f"Response parse failed: {e}", e)
