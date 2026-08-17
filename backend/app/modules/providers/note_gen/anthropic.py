"""Anthropic note generation provider -- real implementation.

Stage 1 uses a compact, three-shard internal wire format to avoid regenerating
an 8k+ token tool call. Stage 2 retains the original full response contract.
Both paths return the same public ``Note`` model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.types import Note, ProviderError, Template, Transcript
from app.modules.config.appconfig_client import get_config
from app.modules.providers.base import ChatMessage, NoteGenerationProvider
from app.modules.providers.note_gen.compact_stage1 import (
    Stage1ShardSpec,
    compact_response_schema,
    hydrate_compact_stage1_shards,
    partition_stage1_template,
    validate_compact_stage1_shard_payload,
)
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
_ENDPOINT = "https://api.anthropic.com/v1/messages"


def _output_ceilings(configured_max_tokens: int) -> tuple[int, ...]:
    """Configured ceiling followed by one bounded truncation retry."""

    escalated = min(max(configured_max_tokens * 4, 16_000), 32_000)
    if escalated > configured_max_tokens:
        return configured_max_tokens, escalated
    return (configured_max_tokens,)


def _compact_shard_ceilings(full_note_ceilings: tuple[int, ...], shard_count: int) -> tuple[int, ...]:
    """Share the configured output budget across concurrent first attempts.

    Three simultaneous calls must not each reserve the full-note token budget.
    A truncated shard alone retries at the configured full-note ceiling and,
    if needed, at the historical escalated ceiling.
    """

    if shard_count <= 1:
        return full_note_ceilings
    configured = full_note_ceilings[0]
    initial = max(100, (configured + shard_count - 1) // shard_count)
    return tuple(dict.fromkeys((initial, *full_note_ceilings)))


@dataclass
class _UsageAccumulator:
    """Aggregate usage from concurrent shards in the caller's context."""

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))


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

        effective_system = system_prompt or NOTE_GEN_SYSTEM_PROMPT
        params = get_config().model_params.note_generation
        ceilings = _output_ceilings(params.max_tokens)

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # Prior-context facts rely on the established full response
                # contract. Compact Stage 1 can represent only current
                # transcript anchors, so it is unsafe for that input.
                if stage == 1 and template.sections and not prior_context_text:
                    return await self._generate_compact_stage1(
                        client=client,
                        transcript=transcript,
                        template=template,
                        output_language=output_language,
                        effective_system=effective_system,
                        prior_context_text=prior_context_text,
                        participants=participants,
                        specialty_prefix=specialty_prefix,
                        encounter_context=encounter_context,
                        temperature=params.temperature,
                        ceilings=ceilings,
                    )

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
                return await self._generate_full_note(
                    client=client,
                    transcript=transcript,
                    template=template,
                    stage=stage,
                    user_prompt=user_prompt,
                    effective_system=effective_system,
                    temperature=params.temperature,
                    ceilings=ceilings,
                )
        except httpx.HTTPError as exc:
            logger.error(
                "Anthropic note gen failed: session=%s error=%s",
                transcript.session_id,
                str(exc),
            )
            raise ProviderError(
                "anthropic",
                f"Note generation failed: {type(exc).__name__}: {exc}",
                exc,
            )
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error(
                "Anthropic response parse failed: session=%s error=%s",
                transcript.session_id,
                str(exc),
            )
            raise ProviderError("anthropic", f"Response parse failed: {exc}", exc)

    async def _generate_compact_stage1(
        self,
        *,
        client: httpx.AsyncClient,
        transcript: Transcript,
        template: Template,
        output_language: str,
        effective_system: str,
        prior_context_text: str | None,
        participants: list[dict] | None,
        specialty_prefix: str | None,
        encounter_context: str | None,
        temperature: float,
        ceilings: tuple[int, ...],
    ) -> Note:
        """Generate at most three compact section shards concurrently."""

        shards = partition_stage1_template(template)
        shard_ceilings = _compact_shard_ceilings(ceilings, len(shards))
        usage = _UsageAccumulator()

        async def run_shard(
            shard: Stage1ShardSpec,
        ) -> tuple[Stage1ShardSpec, dict[str, Any]]:
            prompt = build_user_prompt(
                transcript,
                shard.template,
                stage=1,
                output_language=output_language,
                prior_context_text=prior_context_text,
                participants=participants,
                specialty_prefix=specialty_prefix,
                encounter_context=encounter_context,
                compact_stage1=True,
            )
            payload = await self._generate_compact_shard(
                client=client,
                transcript=transcript,
                shard=shard,
                user_prompt=prompt,
                effective_system=effective_system,
                temperature=temperature,
                ceilings=shard_ceilings,
                usage=usage,
            )
            return shard, payload

        tasks = [asyncio.create_task(run_shard(shard)) for shard in shards]
        try:
            payloads = await asyncio.gather(*tasks)
        except (Exception, asyncio.CancelledError):
            # asyncio.gather does not cancel siblings when one request fails.
            # Stop them so a terminal Stage 1 job cannot consume quota later.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            if usage.input_tokens or usage.output_tokens:
                set_call_usage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    model=_MODEL,
                )

        return hydrate_compact_stage1_shards(
            payloads,
            transcript,
            template,
            provider_name="anthropic",
        )

    async def _generate_compact_shard(
        self,
        *,
        client: httpx.AsyncClient,
        transcript: Transcript,
        shard: Stage1ShardSpec,
        user_prompt: str,
        effective_system: str,
        temperature: float,
        ceilings: tuple[int, ...],
        usage: _UsageAccumulator,
    ) -> dict[str, Any]:
        """Generate one shard; retry only this shard on truncation."""

        for attempt_max_tokens in ceilings:
            response = await client.post(
                _ENDPOINT,
                headers={
                    "x-api-key": _ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "max_tokens": attempt_max_tokens,
                    "temperature": temperature,
                    "system": effective_system,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "tools": [
                        {
                            "name": "emit_clinical_note",
                            "description": (
                                "Emit this section group of the structured clinical note under the active system rules."
                            ),
                            "input_schema": compact_response_schema(shard.section_ids),
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
            attempt_usage = data.get("usage") or {}
            usage.add(attempt_usage)
            logger.info(
                "Anthropic model call completed: session=%s provider=anthropic "
                "model=%s stage=1 shard=%s max_tokens=%d stop_reason=%s "
                "input_tokens=%d output_tokens=%d",
                transcript.session_id,
                _MODEL,
                shard.name,
                attempt_max_tokens,
                data.get("stop_reason", "unknown"),
                int(attempt_usage.get("input_tokens", 0)),
                int(attempt_usage.get("output_tokens", 0)),
            )

            if data.get("stop_reason") == "max_tokens":
                logger.warning(
                    "Anthropic compact Stage 1 shard truncated: session=%s shard=%s max_tokens=%d - %s",
                    transcript.session_id,
                    shard.name,
                    attempt_max_tokens,
                    "retrying shard" if attempt_max_tokens != ceilings[-1] else "ceiling exhausted",
                )
                continue

            payload: dict[str, Any] | None = None
            for block in data.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "emit_clinical_note":
                    tool_input = block.get("input")
                    if isinstance(tool_input, dict):
                        payload = tool_input
                    break
            if payload is None:
                for block in data.get("content", []):
                    if "text" in block:
                        decoded = json.loads(block["text"])
                        if isinstance(decoded, dict):
                            payload = decoded
                        break
            if payload is None:
                raise ProviderError(
                    "anthropic",
                    f"No compact tool payload for Stage 1 shard {shard.name}",
                )
            validate_compact_stage1_shard_payload(shard, payload)
            return payload

        raise ProviderError(
            "anthropic",
            f"Stage 1 shard {shard.name} truncated at max_tokens={ceilings[-1]} ({len(transcript.segments)} segments)",
        )

    async def _generate_full_note(
        self,
        *,
        client: httpx.AsyncClient,
        transcript: Transcript,
        template: Template,
        stage: int,
        user_prompt: str,
        effective_system: str,
        temperature: float,
        ceilings: tuple[int, ...],
    ) -> Note:
        """Original full response path, retained for Stage 2."""

        usage = _UsageAccumulator()
        for attempt_max_tokens in ceilings:
            response = await client.post(
                _ENDPOINT,
                headers={
                    "x-api-key": _ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "max_tokens": attempt_max_tokens,
                    "temperature": temperature,
                    "system": effective_system,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "tools": [
                        {
                            "name": "emit_clinical_note",
                            "description": ("Emit the structured clinical note under the active system rules."),
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
            attempt_usage = data.get("usage") or {}
            usage.add(attempt_usage)
            logger.info(
                "Anthropic model call completed: session=%s provider=anthropic "
                "model=%s stage=%d shard=full max_tokens=%d stop_reason=%s "
                "input_tokens=%d output_tokens=%d",
                transcript.session_id,
                _MODEL,
                stage,
                attempt_max_tokens,
                data.get("stop_reason", "unknown"),
                int(attempt_usage.get("input_tokens", 0)),
                int(attempt_usage.get("output_tokens", 0)),
            )
            set_call_usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                model=_MODEL,
            )

            if data.get("stop_reason") == "max_tokens":
                logger.warning(
                    "Anthropic note gen truncated at max_tokens=%d: session=%s segments=%d - %s",
                    attempt_max_tokens,
                    transcript.session_id,
                    len(transcript.segments),
                    "retrying at a higher ceiling" if attempt_max_tokens != ceilings[-1] else "ceiling exhausted",
                )
                continue

            payload_str = None
            for block in data.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "emit_clinical_note":
                    payload_str = json.dumps(block["input"])
                    break
            if payload_str is None:
                for block in data.get("content", []):
                    if "text" in block:
                        payload_str = block["text"]
                        break
            if payload_str is None:
                raise ProviderError("anthropic", "No tool_use or text block in response")
            return parse_note_response(payload_str, transcript, template, stage, "anthropic")

        raise ProviderError(
            "anthropic",
            f"Note generation output truncated at max_tokens={ceilings[-1]} "
            f"({len(transcript.segments)}-segment transcript) - the encounter "
            "is too long for the configured output ceiling.",
        )

    async def generate_text(self, system: str, messages: list[ChatMessage]) -> str:
        """Structural-chat completion against Claude."""

        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")
        if not messages:
            raise ProviderError("anthropic", "generate_text requires at least one message")

        params = get_config().model_params.note_generation
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    _ENDPOINT,
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
                        "messages": [{"role": message.role, "content": message.content} for message in messages],
                    },
                )
                response.raise_for_status()
                data = response.json()

            for block in data.get("content", []):
                if block.get("type") == "text" and "text" in block:
                    return block["text"]
            raise ProviderError("anthropic", "No text block in response")
        except httpx.HTTPError as exc:
            logger.error("Anthropic generate_text failed: error=%s", str(exc))
            raise ProviderError("anthropic", f"generate_text failed: {exc}", exc)
