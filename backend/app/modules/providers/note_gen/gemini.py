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
from app.modules.config.appconfig_client import get_config
from app.modules.providers.base import ChatMessage, NoteGenerationProvider
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_SYSTEM_PROMPT,
    NOTE_RESPONSE_SCHEMA,
    build_user_prompt,
    parse_note_response,
)
from app.modules.providers.usage_context import set_call_usage

logger = logging.getLogger("aurion.providers.note_gen.gemini")

_GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
_MODEL = "gemini-2.5-pro"


class GeminiNoteGenerationProvider(NoteGenerationProvider):
    """Gemini note generation provider."""

    async def generate_note(
        self,
        transcript: Transcript,
        template: Template,
        stage: int,
        output_language: str = "en",
        system_prompt: str | None = None,
        prior_context_text: str | None = None,
        participants: list[dict] | None = None,
        specialty_prefix: str | None = None,
    ) -> Note:
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")

        user_prompt = build_user_prompt(
            transcript,
            template,
            stage,
            output_language,
            prior_context_text=prior_context_text,
            participants=participants,
            specialty_prefix=specialty_prefix,
        )
        # AI-PROMPTS-B — service-assembled system prompt (base +
        # per-physician overlay) when present; bare base constant
        # otherwise.
        effective_system = system_prompt or NOTE_GEN_SYSTEM_PROMPT
        # Read model params from AppConfig at call time (CLAUDE.md
        # §"Runtime Configuration").
        params = get_config().model_params.note_generation
        # #437 — config-driven model id (override → compiled-in default).
        model = get_config().model_versions.gemini or _MODEL

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": _GOOGLE_AI_API_KEY},
                    headers={"Content-Type": "application/json"},
                    json={
                        "systemInstruction": {
                            "parts": [{"text": effective_system}]
                        },
                        "contents": [
                            {"parts": [{"text": user_prompt}]}
                        ],
                        "generationConfig": {
                            "temperature": params.temperature,
                            "maxOutputTokens": params.max_tokens,
                            "responseMimeType": "application/json",
                            # Schema-enforced output — Gemini validates
                            # the response shape server-side and rejects
                            # the generation if it can't conform.
                            "responseSchema": NOTE_RESPONSE_SCHEMA,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                usage = data.get("usageMetadata") or {}
                set_call_usage(
                    input_tokens=int(usage.get("promptTokenCount", 0)),
                    output_tokens=int(usage.get("candidatesTokenCount", 0)),
                    model=model,
                )
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return parse_note_response(content, transcript, template, stage, "gemini")

        except httpx.HTTPError as e:
            logger.error("Gemini note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("gemini", f"Note generation failed: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Gemini response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("gemini", f"Response parse failed: {e}", e)

    async def generate_text(
        self, system: str, messages: list[ChatMessage]
    ) -> str:
        """Structural-chat completion against Gemini.

        Used by the conversational template authoring service. Gemini's
        REST API uses `systemInstruction` for the system prompt and
        `contents` for the alternating turns. We map `assistant` → `model`
        because that's Gemini's convention.
        """
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")
        if not messages:
            raise ProviderError("gemini", "generate_text requires at least one message")

        params = get_config().model_params.note_generation
        # #437 — config-driven model id (override → compiled-in default).
        model = get_config().model_versions.gemini or _MODEL
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": _GOOGLE_AI_API_KEY},
                    json={
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [
                            {
                                "role": "user" if m.role == "user" else "model",
                                "parts": [{"text": m.content}],
                            }
                            for m in messages
                        ],
                        "generationConfig": {
                            "temperature": params.temperature,
                            "maxOutputTokens": params.max_tokens,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

        except httpx.HTTPError as e:
            logger.error("Gemini generate_text failed: error=%s", str(e))
            raise ProviderError("gemini", f"generate_text failed: {e}", e)
        except (KeyError, IndexError) as e:
            logger.error("Gemini generate_text parse failed: error=%s", str(e))
            raise ProviderError("gemini", f"generate_text parse failed: {e}", e)
