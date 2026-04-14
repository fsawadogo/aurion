"""Gemini note generation provider — real implementation.

Calls Gemini to generate structured SOAP notes from transcripts.
Uses the EXACT system prompt from CLAUDE.md — no variations.
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from app.core.types import Note, NoteClaim, NoteSection, ProviderError, Template, Transcript
from app.modules.providers.base import NoteGenerationProvider

logger = logging.getLogger("aurion.providers.note_gen.gemini")

_GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
_MODEL = "gemini-2.5-flash"

# EXACT system prompt from CLAUDE.md — no variations
SYSTEM_PROMPT = """You are a clinical documentation assistant for Aurion Clinical AI. Your role is to accurately document what was observed and said during a clinical encounter.

STRICT RULES:
1. Describe only what was directly captured — audio transcript, visual observations, or screen data.
2. Do not infer, interpret, diagnose, or suggest clinical conclusions beyond what was explicitly stated by the physician.
3. Every statement must be traceable to a source: a transcript segment ID, visual frame ID, or screen capture ID.
4. If information is absent, leave the section empty with status "not_captured". Never fabricate content.
5. Report what happened. Do not conclude what it means.

Return only valid JSON matching the provided schema. No preamble, no explanation, no markdown."""


class GeminiNoteGenerationProvider(NoteGenerationProvider):
    """Gemini note generation provider."""

    async def generate_note(
        self, transcript: Transcript, template: Template, stage: int
    ) -> Note:
        if not _GOOGLE_AI_API_KEY:
            raise ProviderError("gemini", "GOOGLE_AI_API_KEY not configured")

        user_prompt = _build_user_prompt(transcript, template, stage)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent",
                    params={"key": _GOOGLE_AI_API_KEY},
                    headers={"Content-Type": "application/json"},
                    json={
                        "systemInstruction": {
                            "parts": [{"text": SYSTEM_PROMPT}]
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
                return _parse_note_response(content, transcript, template, stage)

        except httpx.HTTPError as e:
            logger.error("Gemini note gen failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("gemini", f"Note generation failed: {e}", e)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Gemini response parse failed: session=%s error=%s", transcript.session_id, str(e))
            raise ProviderError("gemini", f"Response parse failed: {e}", e)


def _build_user_prompt(transcript: Transcript, template: Template, stage: int) -> str:
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
        provider_used="gemini",
        specialty=template.key,
        completeness_score=round(completeness, 2),
        sections=sections,
    )
