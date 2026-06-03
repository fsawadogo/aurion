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
from app.modules.config.appconfig_client import get_config
from app.modules.providers.base import ChatMessage, NoteGenerationProvider
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
        self,
        transcript: Transcript,
        template: Template,
        stage: int,
        output_language: str = "en",
        system_prompt: str | None = None,
    ) -> Note:
        if not _OPENAI_API_KEY:
            raise ProviderError("openai", "OPENAI_API_KEY not configured")

        user_prompt = build_user_prompt(transcript, template, stage, output_language)
        # AI-PROMPTS-B — use the service-assembled system prompt when
        # provided (base + per-physician overlay). Falls back to the
        # bare base constant for callers that haven't (yet) wired the
        # overlay path. The base prompt itself is never mutated; the
        # overlay is appended below a separator at assembly time.
        effective_system = system_prompt or NOTE_GEN_SYSTEM_PROMPT
        # Read model params from AppConfig at call time so admins can
        # tune temperature / max_tokens at runtime without a redeploy
        # (CLAUDE.md §"Runtime Configuration"). Falls back to the
        # documented 0.1 / 2000 defaults if AppConfig is unreachable.
        params = get_config().model_params.note_generation

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
                        "temperature": params.temperature,
                        "max_tokens": params.max_tokens,
                        "messages": [
                            {"role": "system", "content": effective_system},
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

    async def generate_text(
        self, system: str, messages: list[ChatMessage]
    ) -> str:
        """Structural-chat completion against GPT-4o.

        Used by the conversational template authoring service. The
        system prompt becomes a `system` message; user/assistant turns
        follow in order. No response_format constraint — JSON drafts
        are emitted inline in fenced code blocks per the system prompt.
        """
        if not _OPENAI_API_KEY:
            raise ProviderError("openai", "OPENAI_API_KEY not configured")
        if not messages:
            raise ProviderError("openai", "generate_text requires at least one message")

        params = get_config().model_params.note_generation
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "max_tokens": params.max_tokens,
                        "temperature": params.temperature,
                        "messages": [
                            {"role": "system", "content": system},
                            *[
                                {"role": m.role, "content": m.content}
                                for m in messages
                            ],
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

        except httpx.HTTPError as e:
            logger.error("OpenAI generate_text failed: error=%s", str(e))
            raise ProviderError("openai", f"generate_text failed: {e}", e)
        except (KeyError, IndexError) as e:
            logger.error("OpenAI generate_text parse failed: error=%s", str(e))
            raise ProviderError("openai", f"generate_text parse failed: {e}", e)
