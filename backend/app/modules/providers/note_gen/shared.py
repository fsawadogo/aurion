"""Shared logic for note generation providers.

All three providers (OpenAI, Anthropic, Gemini) use the same system prompt,
build the same user prompt, and parse the LLM response into the same Note
schema.  Provider-specific code is limited to the HTTP call and response
extraction -- everything else lives here.
"""

from __future__ import annotations

import json
import logging

from app.core.types import Note, NoteClaim, NoteSection, Template, Transcript

logger = logging.getLogger("aurion.note_gen.parse")

# JSON Schema for the Note response. Used by providers that support
# schema-enforced output (Anthropic tool_use, Gemini responseSchema)
# so the model can't return malformed shapes. OpenAI gets the same
# guarantees via response_format: json_object (no per-field schema
# but valid JSON only). Mirrors the Note Pydantic model surface that
# parse_note_response will validate against.
NOTE_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["populated", "pending_video", "not_captured"],
                    },
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "source_type": {
                                    "type": "string",
                                    "enum": ["transcript", "visual", "screen"],
                                },
                                "source_id": {"type": "string"},
                                "source_quote": {"type": "string"},
                            },
                            "required": [
                                "id",
                                "text",
                                "source_type",
                                "source_id",
                                "source_quote",
                            ],
                        },
                    },
                },
                "required": ["id", "status", "claims"],
            },
        }
    },
    "required": ["sections"],
}


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


_LANGUAGE_NAMES = {"en": "English", "fr": "French"}


def render_participants_block(participants: list[dict] | None) -> str:
    """Render the ENCOUNTER PARTICIPANTS prompt block (#275).

    Fires whenever ``participants`` is non-empty. The enrolling clinician
    is an implicit second speaker, so even a single chip means the
    encounter has more than one voice to attribute — the historic
    ``len(...) > 1`` gate misfired for a single team member and is fixed
    here.

    Rendering, per chip:
      * Named member (``name`` present) → ``- {name} ({Role})``.
      * Anonymous role chip (``name`` is ``None``/empty) → role-only
        ``- ({Role}), unnamed``. A name is NEVER synthesized for an
        unnamed speaker — descriptive-mode / citation traceability allows
        role-only attribution for unnamed speakers and named attribution
        only for named members.

    Returns ``""`` when there are no participants so cold-path sessions
    produce a byte-identical prompt to the pre-#275 build.
    """
    if not participants:
        return ""
    lines: list[str] = []
    for p in participants:
        role = str(p.get("role", "") or "").replace("_", " ").title()
        name = p.get("name")
        if name:
            lines.append(f"- {name} ({role})")
        else:
            lines.append(f"- ({role}), unnamed")
    roles_list = "\n".join(lines)
    return (
        f"ENCOUNTER PARTICIPANTS:\n{roles_list}\n\n"
        "More than one person is present. Attribute statements to the "
        "appropriate role when identifiable from context (e.g., "
        "'Nurse noted...', 'Resident reported...'). When the speaker is "
        "ambiguous, use 'It was noted...' rather than attributing to a "
        "specific person. Never attribute a statement to a named person "
        "unless their name appears above.\n\n"
    )


def build_user_prompt(
    transcript: Transcript,
    template: Template,
    stage: int,
    output_language: str = "en",
    prior_context_text: str | None = None,
    participants: list[dict] | None = None,
) -> str:
    """Build the user prompt with transcript and template context.

    ``output_language`` controls the language of the generated note content.
    The transcript may be in either language (FR or EN); the note is written
    in the requested output language regardless of what was spoken.

    ``prior_context_text`` (#61, full slice) — when non-empty, the
    rendered prior-encounter block from
    :func:`app.modules.longitudinal_context.render_prior_context_block`
    is injected just above the transcript so the model reads it as
    additional ground-truth context. Empty / ``None`` skips the section
    entirely so cold-start sessions produce a byte-identical prompt to
    the pre-#61 build.

    ``participants`` (#275) — the encounter participant chips
    ({name, role, source, is_persistent}). When non-empty an ENCOUNTER
    PARTICIPANTS block is injected (see :func:`render_participants_block`)
    so the model can attribute statements by role/name. Empty / ``None``
    skips it entirely (byte-identical to the pre-#275 build).
    """
    sections_spec = json.dumps(
        [{"id": s.id, "title": s.title, "required": s.required} for s in template.sections],
        indent=2,
    )
    segments_text = "\n".join(
        f"[{s.id}] ({s.start_ms}ms-{s.end_ms}ms): {s.text}"
        for s in transcript.segments
    )
    language_instruction = ""
    if output_language != "en":
        lang = _LANGUAGE_NAMES.get(output_language, output_language)
        language_instruction = (
            f"\nWrite ALL note content — claim text and section titles — in {lang}. "
            "Keep the JSON structure, section \"id\" values, and status values "
            "exactly as specified in English (do not translate keys or ids).\n"
        )
    prior_block = ""
    if prior_context_text:
        prior_block = f"{prior_context_text}\n\n"
    participants_block = render_participants_block(participants)
    return f"""Generate a Stage {stage} clinical note for specialty: {template.key}
{language_instruction}
Template sections (generate each):
{sections_spec}

{participants_block}{prior_block}Transcript segments:
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
    model_section_ids = set(existing_ids)
    backfilled = 0
    for ts in template.sections:
        if ts.id not in existing_ids:
            sections.append(
                NoteSection(id=ts.id, title=ts.title, status="not_captured", claims=[])
            )
            backfilled += 1

    # Surface silent degradations (#280). A model response that omits
    # template sections — or returns section ids outside the template —
    # gets backfilled to `not_captured`, which previously dropped to a
    # 0.00 note recorded as provider "success" with no signal.
    if backfilled:
        out_of_template = model_section_ids - {ts.id for ts in template.sections}
        logger.warning(
            "note parse backfilled %d/%d template section(s) "
            "(stage=%d provider=%s template=%s out_of_template_ids=%d)",
            backfilled,
            len(template.sections),
            stage,
            provider_name,
            template.key,
            len(out_of_template),
        )

    # Calculate completeness score
    required = [s for s in template.sections if s.required]
    populated = [
        s for s in sections
        if s.status == "populated" and len(s.claims) > 0
        and any(ts.id == s.id and ts.required for ts in template.sections)
    ]
    completeness = len(populated) / len(required) if required else 0.0

    if required and not populated:
        logger.warning(
            "note parse produced 0 populated required sections "
            "(stage=%d provider=%s template=%s) — empty note",
            stage,
            provider_name,
            template.key,
        )

    return Note(
        session_id=transcript.session_id,
        stage=stage,
        version=1,
        provider_used=provider_name,
        specialty=template.key,
        completeness_score=round(completeness, 2),
        sections=sections,
    )
