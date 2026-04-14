"""Shared logic for note generation providers.

All three providers (OpenAI, Anthropic, Gemini) use the same system prompt,
build the same user prompt, and parse the LLM response into the same Note
schema.  Provider-specific code is limited to the HTTP call and response
extraction -- everything else lives here.
"""

from __future__ import annotations

import json

from app.core.types import Note, NoteClaim, NoteSection, Template, Transcript

# EXACT system prompt from CLAUDE.md -- no variations.
# Shared across all note generation providers.
NOTE_GEN_SYSTEM_PROMPT = """You are a clinical documentation assistant for Aurion Clinical AI. Your role is to accurately document what was observed and said during a clinical encounter.

STRICT RULES:
1. Describe only what was directly captured — audio transcript, visual observations, or screen data.
2. Do not infer, interpret, diagnose, or suggest clinical conclusions beyond what was explicitly stated by the physician.
3. Every statement must be traceable to a source: a transcript segment ID, visual frame ID, or screen capture ID.
4. If information is absent, leave the section empty with status "not_captured". Never fabricate content.
5. Report what happened. Do not conclude what it means.

Return only valid JSON matching the provided schema. No preamble, no explanation, no markdown."""


def build_user_prompt(transcript: Transcript, template: Template, stage: int) -> str:
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


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences that some LLMs wrap around JSON output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def parse_note_response(
    content: str,
    transcript: Transcript,
    template: Template,
    stage: int,
    provider_name: str,
) -> Note:
    """Parse the LLM JSON response into a Note object.

    Handles markdown fences, missing sections, and completeness scoring.
    """
    text = strip_markdown_fences(content)
    raw = json.loads(text)
    sections: list[NoteSection] = []

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

    # Ensure all template sections are present
    existing_ids = {s.id for s in sections}
    for ts in template.sections:
        if ts.id not in existing_ids:
            sections.append(
                NoteSection(id=ts.id, title=ts.title, status="not_captured", claims=[])
            )

    # Calculate completeness score
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
        provider_used=provider_name,
        specialty=template.key,
        completeness_score=round(completeness, 2),
        sections=sections,
    )
