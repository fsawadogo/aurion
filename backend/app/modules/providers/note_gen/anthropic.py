"""Anthropic note generation provider -- real implementation.

Calls Claude to generate structured SOAP notes from transcripts.
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

logger = logging.getLogger("aurion.providers.note_gen.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"


class AnthropicNoteGenerationProvider(NoteGenerationProvider):
    """Claude note generation provider."""

    async def generate_note(
        self, transcript: Transcript, template: Template, stage: int
    ) -> Note:
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")

        user_prompt = build_user_prompt(transcript, template, stage)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": _ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "max_tokens": 2000,
                        "temperature": 0.1,
                        "system": NOTE_GEN_SYSTEM_PROMPT,
                        "messages": [
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["content"][0]["text"]
                return parse_note_response(content, transcript, template, stage, "anthropic")

        except httpx.HTTPError as e:
            logger.error("Anthropic note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("anthropic", f"Note generation failed: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Anthropic response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("anthropic", f"Response parse failed: {e}", e)
