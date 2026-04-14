"""Anthropic note generation provider — real implementation.

Calls Claude to generate structured SOAP notes from transcripts.
Uses the EXACT system prompt from CLAUDE.md — no variations.
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from app.core.types import Note, NoteClaim, NoteSection, ProviderError, Template, Transcript
from app.modules.providers.base import NoteGenerationProvider

logger = logging.getLogger("aurion.providers.note_gen.anthropic")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-20250514"

# EXACT system prompt from CLAUDE.md — no variations
SYSTEM_PROMPT = """You are a clinical documentation assistant for Aurion Clinical AI. Your role is to accurately document what was observed and said during a clinical encounter.

STRICT RULES:
1. Describe only what was directly captured — audio transcript, visual observations, or screen data.
2. Do not infer, interpret, diagnose, or suggest clinical conclusions beyond what was explicitly stated by the physician.
3. Every statement must be traceable to a source: a transcript segment ID, visual frame ID, or screen capture ID.
4. If information is absent, leave the section empty with status "not_captured". Never fabricate content.
5. Report what happened. Do not conclude what it means.

Return only valid JSON matching the provided schema. No preamble, no explanation, no markdown."""


class AnthropicNoteGenerationProvider(NoteGenerationProvider):
    """Claude note generation provider."""

    async def generate_note(
        self, transcript: Transcript, template: Template, stage: int
    ) -> Note:
        if not _ANTHROPIC_API_KEY:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY not configured")

        user_prompt = _build_user_prompt(transcript, template, stage)

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
                        "system": SYSTEM_PROMPT,
                        "messages": [
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["content"][0]["text"]
                return _parse_note_response(content, transcript, template, stage)

        except httpx.HTTPError as e:
            logger.error("Anthropic note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("anthropic", f"Note generation failed: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Anthropic response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("anthropic", f"Response parse failed: {e}", e)


def _build_user_prompt(transcript: Transcript, template: Template, stage: int) -> str:
    """Build the user prompt with transcript and template context."""
    sections_spec = json.dumps(
        [{"id": s.id, "title": s.title, "required": s.required} for s in template.sections],
        indent=2,
    )
    segments_text = "\n".join(
        f"[{s.id}] ({s.start_ms}ms-{s.end_ms}ms): {s.text}"
        for s in transcript.segments
    )
    return f"""Generate a Stage {stage} clinical note for specialty: {template.key}

Template sections (generate each):
{sections_spec}

Transcript segments:
{segments_text}

Return JSON with this schema:
{{
  "sections": [
    {{
      "id": "<section_id>",
      "title": "<section_title>",
      "status": "populated" | "pending_video" | "not_captured",
      "claims": [
        {{
          "id": "<claim_id>",
          "text": "<descriptive claim>",
          "source_type": "transcript",
          "source_id": "<segment_id>",
          "source_quote": "<exact quote from transcript>"
        }}
      ]
    }}
  ]
}}

For Stage 1: mark imaging/visual sections as "pending_video" if no transcript evidence. Mark as "not_captured" only if no content exists for that section."""


def _parse_note_response(
    content: str, transcript: Transcript, template: Template, stage: int
) -> Note:
    """Parse the LLM JSON response into a Note object."""
    # Handle potential markdown wrapping
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    raw = json.loads(text)
    sections = []

    for raw_section in raw.get("sections", []):
        claims = [
            NoteClaim(
                id=c.get("id", f"claim_{raw_section['id']}_{i}"),
                text=c.get("text", ""),
                source_type=c.get("source_type", "transcript"),
                source_id=c.get("source_id", ""),
                source_quote=c.get("source_quote", ""),
            )
            for i, c in enumerate(raw_section.get("claims", []))
        ]
        sections.append(
            NoteSection(
                id=raw_section.get("id", ""),
                title=raw_section.get("title", ""),
                status=raw_section.get("status", "not_captured"),
                claims=claims,
            )
        )

    # Ensure all template sections present
    existing_ids = {s.id for s in sections}
    for ts in template.sections:
        if ts.id not in existing_ids:
            sections.append(
                NoteSection(id=ts.id, title=ts.title, status="not_captured", claims=[])
            )

    required = [s for s in template.sections if s.required]
    populated = [
        s for s in sections
        if s.status == "populated" and len(s.claims) > 0
        and any(ts.id == s.id and ts.required for ts in template.sections)
    ]
    completeness = len(populated) / len(required) if required else 0.0

    return Note(
        session_id=transcript.session_id,
        stage=stage,
        version=1,
        provider_used="anthropic",
        specialty=template.key,
        completeness_score=round(completeness, 2),
        sections=sections,
    )
