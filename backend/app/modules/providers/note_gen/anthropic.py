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
from app.modules.config.appconfig_client import get_config
from app.modules.providers.base import ChatMessage, NoteGenerationProvider
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_SYSTEM_PROMPT,
    NOTE_RESPONSE_SCHEMA,
    build_user_prompt,
    parse_note_response,
)
from app.modules.providers.usage_context import set_call_usage

logger = logging.getLogger("aurion.providers.note_gen.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"


class AnthropicNoteGenerationProvider(NoteGenerationProvider):
    """Claude note generation provider."""

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
        encounter_context: str | None = None,
    ) -> Note:
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")

        user_prompt = build_user_prompt(
            transcript,
            template,
            stage,
            output_language,
            prior_context_text=prior_context_text,
            participants=participants,
            specialty_prefix=specialty_prefix,
            encounter_context=encounter_context,
        )
        # AI-PROMPTS-B — service-assembled system prompt (base +
        # per-physician overlay) when present; bare base constant
        # otherwise. The base text is never mutated.
        effective_system = system_prompt or NOTE_GEN_SYSTEM_PROMPT
        # Read model params from AppConfig at call time (CLAUDE.md
        # §"Runtime Configuration") — admins can tune temp / max_tokens
        # without a redeploy.
        params = get_config().model_params.note_generation

        try:
            # 300s: grounded synthesis over a full note with the enriched
            # specialty prompt + few-shot can exceed the old 120s ceiling —
            # a ReadTimeout there surfaced as a blank "Note generation failed:"
            # and a 500 on upload. Well within the 5-min Stage 2 budget.
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": _ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "max_tokens": params.max_tokens,
                        "temperature": params.temperature,
                        "system": effective_system,
                        "messages": [
                            {"role": "user", "content": user_prompt},
                        ],
                        # Force the model to emit the note via a tool call.
                        # Anthropic guarantees the `input` matches the
                        # `input_schema` when tool_choice pins the tool —
                        # eliminates an entire class of JSON parse / shape
                        # errors that previously surfaced as STAGE1_FAILED.
                        "tools": [
                            {
                                "name": "emit_clinical_note",
                                "description": (
                                    "Emit the structured clinical note built "
                                    "from the transcript per the descriptive-"
                                    "mode rules in the system prompt."
                                ),
                                "input_schema": NOTE_RESPONSE_SCHEMA,
                            }
                        ],
                        "tool_choice": {
                            "type": "tool",
                            "name": "emit_clinical_note",
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                usage = data.get("usage") or {}
                set_call_usage(
                    input_tokens=int(usage.get("input_tokens", 0)),
                    output_tokens=int(usage.get("output_tokens", 0)),
                    model=_MODEL,
                )
                # Tool-use response: content blocks include a tool_use
                # block whose `input` is the schema-validated JSON. Fall
                # back to a text block if the model declined the tool
                # (shouldn't happen with tool_choice, but defensive).
                payload_str = None
                for block in data.get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "emit_clinical_note":
                        payload_str = json.dumps(block["input"])
                        break
                if payload_str is None:
                    # Defensive fallback — should never hit with forced
                    # tool_choice but tolerate older API shapes (text
                    # block, or a bare text-bearing block) for resilience.
                    for block in data.get("content", []):
                        if "text" in block:
                            payload_str = block["text"]
                            break
                if payload_str is None:
                    raise ProviderError("anthropic", "No tool_use or text block in response")
                return parse_note_response(payload_str, transcript, template, stage, "anthropic")

        except httpx.HTTPError as e:
            logger.error("Anthropic note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("anthropic", f"Note generation failed: {type(e).__name__}: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Anthropic response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("anthropic", f"Response parse failed: {e}", e)

    async def generate_text(
        self, system: str, messages: list[ChatMessage]
    ) -> str:
        """Structural-chat completion against Claude.

        Used by the conversational template authoring service. No tools,
        no JSON schema — the model returns plain assistant text. Any
        JSON the service needs is emitted by the model inside fenced
        code blocks per the system prompt, and parsed by the service.
        """
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")
        if not messages:
            raise ProviderError("anthropic", "generate_text requires at least one message")

        params = get_config().model_params.note_generation
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": _ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "max_tokens": params.max_tokens,
                        "temperature": params.temperature,
                        "system": system,
                        "messages": [
                            {"role": m.role, "content": m.content} for m in messages
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()

            for block in data.get("content", []):
                if block.get("type") == "text" and "text" in block:
                    return block["text"]
            raise ProviderError("anthropic", "No text block in response")

        except httpx.HTTPError as e:
            logger.error("Anthropic generate_text failed: error=%s", str(e))
            raise ProviderError("anthropic", f"generate_text failed: {e}", e)
