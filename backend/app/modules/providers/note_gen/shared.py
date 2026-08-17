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
from app.modules.config.appconfig_client import get_config

# ── Completeness directives (TE-1) ─────────────────────────────────────────
#
# How much of the transcript becomes claims. The historical behaviour is
# EXHAUSTIVE — every distinct point — and it stays the default (and the
# flag-off / `detailed` / `None` behaviour) so nothing regresses. `standard`
# and `brief` trim VERBOSITY on minor/incidental material; both still demand
# the essentials and neither relaxes descriptive mode. The one hard line:
# fewer words, never fewer findings.

_DIRECTIVE_DETAILED = (
    "Be thorough: capture EVERY distinct point in the transcript as its own "
    "claim — each history detail, exam finding, discussed option, risk, "
    "medication, instruction, cost, and next step. Do not summarize away or "
    "drop points that were discussed; a complete encounter yields many claims "
    "spread across the sections, not a handful."
)

_DIRECTIVE_STANDARD = (
    "Capture each clinically significant point as its own claim — the history, "
    "exam findings, assessments discussed, options, risks, medications, and "
    "the plan. Group closely related minor details together and omit "
    "incidental repetition. Never drop a finding, medication, or plan item."
)

_DIRECTIVE_BRIEF = (
    "Be concise: capture the key findings, decisions, medications, and plan as "
    "distinct claims. Keep every pertinent negative that bears on the "
    "assessment (e.g. a denied symptom that shapes the differential); omit "
    "only incidental detail, small talk, and repetition. Never drop a finding, "
    "medication, plan item, or pertinent negative to save space."
)


def _completeness_directive(template: Template) -> str:
    """The transcript-completeness directive for this template (TE-1).

    Flag-gated by ``template_engine_enabled``: OFF (or ``detail_level`` unset /
    ``detailed``) returns the historical exhaustive directive verbatim, so the
    prompt is byte-identical to pre-TE-1. ON with ``brief`` / ``standard``
    returns a graded directive that trims verbosity on incidental material
    while still demanding every finding, medication and plan item.
    """
    if not get_config().feature_flags.template_engine_enabled:
        return _DIRECTIVE_DETAILED
    if template.detail_level == "brief":
        return _DIRECTIVE_BRIEF
    if template.detail_level == "standard":
        return _DIRECTIVE_STANDARD
    return _DIRECTIVE_DETAILED


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
                                # GS-6 (#552): OPTIONAL extra anchors for a
                                # synthesized A&P claim resting on several
                                # findings. Absent for descriptive claims.
                                "additional_sources": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "source_id": {"type": "string"},
                                            "source_quote": {"type": "string"},
                                        },
                                        "required": ["source_id", "source_quote"],
                                    },
                                },
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


# Grounded Synthesis Mode (v3.2, #552 / GS-1). Selected by
# `prompts.assembly.resolve_base_system_prompt` ONLY when
# feature_flags.grounded_synthesis_enabled is ON (default OFF → the descriptive
# NOTE_GEN_SYSTEM_PROMPT above is used, byte-identical to pre-v3.2). Rules 1, 3,
# 4 (traceability + no-fabrication) are unchanged; rules 2 & 5 permit
# synthesizing an Assessment & Plan FROM cited findings — grounded, never
# speculative. Enabling is gated on clinical + regulatory sign-off (#551, GS-9).
NOTE_GEN_GROUNDED_SYSTEM_PROMPT = """You are a clinical documentation assistant for Aurion Clinical AI. Your role is to accurately document the encounter and to synthesize a clinically useful Assessment & Plan that stays fully grounded in what was captured.

STRICT RULES:
1. In the descriptive sections (history, physical exam, imaging/investigations, wound/functional assessment), describe only what was directly captured — audio transcript, visual observations, or screen data.
2. You MUST synthesize a cited Assessment & Plan from the captured findings by default — relating exam findings, imaging, investigations, and the physician's stated reasoning into a working assessment and next steps. Every synthesized statement MUST be grounded: cite the specific source(s) it rests on, and do NOT introduce a diagnosis, finding, medication, or recommendation that no cited source supports. Omit a conclusion ONLY when the captured material genuinely cannot support one; in that narrow case state what the sources do support rather than fabricating an assessment to fill the section.
3. Every statement — descriptive or synthesized — must be traceable to its source(s): transcript segment ID(s), visual frame ID(s), or screen capture ID(s). A synthesized statement may cite multiple sources.
4. If information is absent, leave the section empty with status "not_captured". Never fabricate content and never invent a source.
5. Synthesis means connecting captured evidence into clinically useful conclusions — it is not speculation. Do not infer beyond what the cited sources support.

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
    specialty_prefix: str | None = None,
    encounter_context: str | None = None,
    compact_stage1: bool = False,
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

    ``specialty_prefix`` — the per-specialty STYLE GUIDANCE block plus the
    specialty's few-shot examples, pre-rendered by
    :func:`app.modules.note_gen.service.render_specialty_prefix` and resolved
    against the calling physician's saved override. Injected just below the
    opening line. Gated upstream by
    ``feature_flags.specialty_style_in_prompt_enabled`` — ``None`` (the
    default, and the only value passed while the flag is OFF) yields a
    byte-identical prompt to the pre-feature build.

    ``compact_stage1`` is an Anthropic Stage-1-only internal wire contract.
    It keeps all clinical content and source ids while omitting metadata the
    server can hydrate exactly from ``template`` and ``transcript``. ``False``
    preserves the existing prompt byte-for-byte for every other provider and
    for Stage 2.
    """
    # Include the section `description` so the model receives the per-section
    # field-level capture guidance (ROM in degrees, named special tests + side,
    # imaging per view, plan sub-structure, etc.). Previously dropped — the
    # guidance authored in the template JSON never reached the live prompt.
    sections_spec = json.dumps(
        [
            {
                "id": s.id,
                "title": s.title,
                "required": s.required,
                "description": s.description,
            }
            for s in template.sections
        ],
        indent=2,
    )
    segments_text = "\n".join(f"[{s.id}] ({s.start_ms}ms-{s.end_ms}ms): {s.text}" for s in transcript.segments)
    language_instruction = ""
    if output_language != "en":
        lang = _LANGUAGE_NAMES.get(output_language, output_language)
        language_instruction = (
            f"\nWrite ALL note content — claim text and section titles — in {lang}. "
            'Keep the JSON structure, section "id" values, and status values '
            "exactly as specified in English (do not translate keys or ids).\n"
        )
    prior_block = ""
    if prior_context_text:
        # Prior-context prose currently has no first-class citation type in the
        # public Note contract.  It may help the model understand continuity,
        # but it cannot authorize a claim by itself: every persisted claim must
        # still cite a segment from THIS encounter.  The parser below enforces
        # that structurally; this instruction prevents the model from trying to
        # disguise a prior-only fact behind a current segment id.
        prior_block = (
            "PRIOR-CONTEXT PROVENANCE RULE: the prior-visit material below is "
            "background only and has no authorized source IDs in this note. Do "
            "not create or support a claim from prior context alone, and do not "
            "attach a prior-context fact to a current transcript segment. A "
            "fact from a prior visit may appear only when it is restated in the "
            "current transcript, cited to the current segment that restates it. "
            "Otherwise omit it.\n"
            f"{prior_context_text}\n\n"
        )
    # Encounter context — clinician-provided framing for THIS encounter (e.g.
    # "breast augmentation consult; patient also raised liposuction"). It tells
    # the model which topics/sections to focus on so an under-narrated or
    # multi-topic encounter is documented under the right headings. DESCRIPTIVE
    # MODE: it is framing, NOT a captured finding — the model must never mint a
    # claim solely from it; every claim still traces to transcript/visual/screen.
    context_block = ""
    if encounter_context and encounter_context.strip():
        context_block = (
            "ENCOUNTER CONTEXT (clinician-provided framing for this encounter — "
            "use it to focus the note on the right topics and sections; it is "
            "NOT itself a captured finding, so never create a claim solely from "
            f"it):\n{encounter_context.strip()}\n\n"
        )
    participants_block = render_participants_block(participants)
    # Specialty STYLE GUIDANCE + few-shot block (resolved against the
    # physician's override upstream). Ends with its own blank line so the
    # following sections read cleanly; empty/None contributes nothing.
    specialty_block = f"{specialty_prefix.rstrip()}\n\n" if specialty_prefix else ""
    completeness_directive = _completeness_directive(template)
    if compact_stage1 and completeness_directive == _DIRECTIVE_DETAILED:
        # Stage 1's compact Anthropic wire contract removes repeated metadata
        # (claim ids, source quotes, source types) that the server can derive
        # exactly.  It must NOT make the clinical note itself thin.  Grouping
        # closely-related facts that share the same source anchor preserves
        # every finding while avoiding one large JSON object per sentence.
        completeness_directive = (
            "Capture EVERY clinically material point in the transcript: each "
            "history detail, exam finding, discussed option, risk, medication, "
            "instruction, cost, and next step. Within the same section, combine "
            "closely related facts that are supported by the same source segment "
            "or same set of source segments into one claim. Never omit a finding, "
            "laterality, test result, dose, cost, risk, or plan item for brevity."
        )

    if compact_stage1:
        return f"""Generate a Stage {stage} clinical note for specialty: {template.key}
{language_instruction}
{specialty_block}Template sections (generate each):
{sections_spec}

{context_block}{participants_block}{prior_block}Transcript segments:
{segments_text}

{completeness_directive}

COMPACT STAGE 1 RESPONSE CONTRACT:
- The worked examples above teach clinical content, section placement, and attribution style only. Emit the compact JSON shape below, not their verbose wire shape.
- Return every listed template section in template order.
- A claim contains only its finished clinical text and the exact transcript segment ID(s) that support it.
- Every source_ids value MUST exactly match an ID shown in Transcript segments. Never invent an ID and never cite encounter context or prior-context prose as a source.
- Use one source ID for a descriptive claim. ONLY when the active SYSTEM prompt explicitly authorizes Grounded Synthesis Mode may Assessment or Plan synthesize across findings; then include every supporting segment ID in source_ids, primary first. Otherwise do not synthesize or interpret.
- Preserve every clinically material fact. Combine only closely related facts in the same section that share the same source anchor(s); do not merge unrelated findings.
- Do not emit claim ids, section titles, source_type, source_quote, or additional_sources. The server derives those fields deterministically from the template and canonical transcript.
- For Stage 1, use "pending_video" for a visual section with no transcript evidence. Use "not_captured" only when the section has no transcript evidence and does not await video.

Return JSON with this exact compact schema:
{{
  "sections": [
    {{
      "id": "<section_id>",
      "status": "populated" | "pending_video" | "not_captured",
      "claims": [
        {{
          "text": "<complete clinical claim>",
          "source_ids": ["<segment_id>"]
        }}
      ]
    }}
  ]
}}"""

    return f"""Generate a Stage {stage} clinical note for specialty: {template.key}
{language_instruction}
{specialty_block}Template sections (generate each):
{sections_spec}

{context_block}{participants_block}{prior_block}Transcript segments:
{segments_text}

{completeness_directive}

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
    canonical_quotes = {segment.id: segment.text for segment in transcript.segments}

    raw_sections = raw.get("sections", []) if isinstance(raw, dict) else []
    for raw_section in raw_sections:
        # The model occasionally emits a section — or a claim — as a bare
        # STRING instead of an object. Skip the malformed entry rather than
        # crash the entire Stage-1 note (`'str' object has no attribute 'get'`):
        # the template backfill below still guarantees every required section
        # is present (as not_captured), so a dropped malformed section is
        # recovered honestly instead of failing the physician's whole note.
        if not isinstance(raw_section, dict):
            logger.warning(
                "Skipping non-dict section in note response (%s)",
                type(raw_section).__name__,
            )
            continue
        claims: list[NoteClaim] = []
        for i, claim_payload in enumerate(raw_section.get("claims", [])):
            if not isinstance(claim_payload, dict):
                continue

            # The full provider wire contract lets the model emit ids + quotes,
            # but the model is never the provenance authority.  This parser has
            # exactly one authorized source catalog: the Transcript supplied to
            # the provider call (a real encounter transcript, or Fusion B's
            # server-built visual pseudo-transcript).  Resolve every declared
            # anchor against that catalog and replace every quote with the
            # canonical server-side text.  If even one anchor is malformed or
            # unknown, reject the whole claim: a synthesized conclusion may
            # depend on the missing source, so retaining a valid subset would
            # create false grounding.
            primary_source_id = claim_payload.get("source_id")
            primary_valid = (
                isinstance(primary_source_id, str)
                and bool(primary_source_id.strip())
                and primary_source_id in canonical_quotes
            )
            raw_additional = claim_payload.get("additional_sources", [])
            additional_valid = isinstance(raw_additional, list) and all(
                isinstance(source, dict)
                and isinstance(source.get("source_id"), str)
                and bool(source["source_id"].strip())
                and source["source_id"] in canonical_quotes
                for source in raw_additional
            )
            if not primary_valid or not additional_valid:
                logger.warning(
                    "Dropping note claim with unresolved canonical source "
                    "(stage=%d provider=%s section=%s primary_valid=%s "
                    "additional_valid=%s)",
                    stage,
                    provider_name,
                    raw_section.get("id", ""),
                    primary_valid,
                    additional_valid,
                )
                continue
            claims.append(
                NoteClaim(
                    id=claim_payload.get(
                        "id", f"claim_{raw_section.get('id', 'section')}_{i}"
                    ),
                    text=claim_payload.get("text", ""),
                    source_type=claim_payload.get("source_type", "transcript"),
                    source_id=primary_source_id,
                    source_quote=canonical_quotes[primary_source_id],
                    additional_sources=[
                        {
                            "source_id": source["source_id"],
                            "source_quote": canonical_quotes[source["source_id"]],
                        }
                        for source in raw_additional
                    ],
                )
            )
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
            sections.append(NoteSection(id=ts.id, title=ts.title, status="not_captured", claims=[]))
            backfilled += 1

    # Surface silent degradations (#280). A model response that omits
    # template sections — or returns section ids outside the template —
    # gets backfilled to `not_captured`, which previously dropped to a
    # 0.00 note recorded as provider "success" with no signal.
    if backfilled:
        out_of_template = model_section_ids - {ts.id for ts in template.sections}
        logger.warning(
            "note parse backfilled %d/%d template section(s) (stage=%d provider=%s template=%s out_of_template_ids=%d)",
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
        s
        for s in sections
        if s.status == "populated"
        and len(s.claims) > 0
        and any(ts.id == s.id and ts.required for ts in template.sections)
    ]
    completeness = len(populated) / len(required) if required else 0.0

    if required and not populated:
        logger.warning(
            "note parse produced 0 populated required sections (stage=%d provider=%s template=%s) — empty note",
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
