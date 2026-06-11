"""Stage 1 note generation service.

Loads specialty templates from JSON files, builds prompts with the exact
descriptive-mode system prompt, calls the active NoteGenerationProvider via
the registry, calculates completeness scores, and manages note versioning.

No business logic in API route handlers -- routes call these functions only.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.cost_rates import USD_MICROS_PER_DOLLAR, estimate_cost_usd_micros
from app.core.models import NoteVersionModel, SessionModel
from app.core.types import (
    Note,
    NoteClaim,
    NoteSection,
    PriorContextUsedSummary,
    Template,
    Transcript,
)
from app.modules.audit_log.service import get_audit_log_service
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_registry import get_registry
from app.modules.longitudinal_context import (
    PriorContextBlock,
    get_prior_context,
    render_prior_context_block,
)
from app.modules.note_gen import repository as note_repo
from app.modules.note_gen.critique import critique_note
from app.modules.note_gen.few_shot import get_few_shot_examples, render_examples_block
from app.modules.note_gen.specialty_style import get_specialty_style
from app.modules.prompts import assemble_prompt_for_session
from app.modules.providers.note_gen.shared import render_participants_block
from app.modules.providers.usage_context import consume_call_usage
from app.modules.providers.usage_service import get_provider_usage_service

logger = logging.getLogger("aurion.note_gen")

# ── System Prompt -- exact text from CLAUDE.md, no variations ─────────────

NOTE_GENERATION_SYSTEM_PROMPT = (
    "You are a clinical documentation assistant for Aurion Clinical AI. "
    "Your role is to accurately document what was observed and said during "
    "a clinical encounter.\n"
    "\n"
    "STRICT RULES:\n"
    "1. Describe only what was directly captured \u2014 audio transcript, "
    "visual observations, or screen data.\n"
    "2. Do not infer, interpret, diagnose, or suggest clinical conclusions "
    "beyond what was explicitly stated by the physician.\n"
    "3. Every statement must be traceable to a source: a transcript segment "
    "ID, visual frame ID, or screen capture ID.\n"
    "4. If information is absent, leave the section empty with status "
    '"not_captured". Never fabricate content.\n'
    "5. Report what happened. Do not conclude what it means.\n"
    "\n"
    "Return only valid JSON matching the provided schema. No preamble, "
    "no explanation, no markdown."
)

# Descriptive-mode reinforcement that gets appended to the system prompt
# at call time ONLY when prior-encounter context is being fed to the
# model (#61, full slice). Kept OUT of the registry so the prompt
# safety-lock test (``test_descriptive_mode_phrases_locked`` in
# tests/integration/test_me_prompts.py) sees the unchanged base catalog
# entry; the concatenation happens here, in one place, in
# ``generate_stage1_note``.
#
# Why a runtime concatenation and not a registry edit?
#   * The base prompt must stay byte-identical across every Stage 1
#     call (the safety test pins literal substrings). Mutating it via
#     the registry forces every test fixture + every replacement-mode
#     physician override to learn about the new sentence.
#   * Prior context is the only branch where this sentence has any
#     meaning; gluing it on only when prior context is present keeps
#     the prompt minimal for the cold-start case.
_PRIOR_CONTEXT_SYSTEM_SUFFIX = (
    "\n\n"
    "When prior visits are listed, you may reference them factually "
    "(for example 'patient reports continued pain since prior visit "
    "on YYYY-MM-DD'). Do not infer trends or trajectories — only "
    "state what the prior note recorded."
)

# ── Template Loading ──────────────────────────────────────────────────────

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_templates_cache: dict[str, Template] = {}


def load_templates() -> dict[str, Template]:
    """Load all specialty templates from JSON files in app/modules/note_gen/templates/.

    Templates are cached after first load. Call _clear_template_cache()
    in tests to reset.
    """
    if _templates_cache:
        return _templates_cache

    if not _TEMPLATES_DIR.exists():
        logger.warning("Templates directory not found: %s", _TEMPLATES_DIR)
        return _templates_cache

    for template_file in sorted(_TEMPLATES_DIR.glob("*.json")):
        # Skip few-shot example files (templates/{key}.examples.json) —
        # they live in the same directory but parse as examples, not
        # as Templates. See few_shot.py.
        if template_file.name.endswith(".examples.json"):
            continue
        try:
            raw = json.loads(template_file.read_text(encoding="utf-8"))
            template = Template(**raw)
            _templates_cache[template.key] = template
            logger.info(
                "Loaded template: %s (%d sections)", template.key, len(template.sections)
            )
        except Exception as exc:
            logger.error("Failed to load template %s: %s", template_file.name, exc)

    return _templates_cache


def _clear_template_cache() -> None:
    """Clear the template cache. For testing only."""
    _templates_cache.clear()


def get_template(specialty: str) -> Template:
    """Get a specialty template by key.

    Resolution order (#72): runtime admin override (in-memory cache, fed
    by the admin CRUD + ~10s poller) > disk-bundled JSON. Falls back to
    'general' (same order) if the requested specialty is not found.
    Raises ValueError if no template is available at all.
    """
    # Local import — template_override_cache imports core only, but keeping
    # the dependency out of module import time preserves the existing
    # import graph for the many service.py consumers.
    from app.modules.note_gen.template_override_cache import get_cached_override

    override = get_cached_override(specialty)
    if override is not None:
        return override

    templates = load_templates()

    template = templates.get(specialty)
    if template:
        return template

    general_override = get_cached_override("general")
    if general_override is not None:
        logger.warning(
            "Specialty template '%s' not found, falling back to 'general' (override)",
            specialty,
        )
        return general_override

    general = templates.get("general")
    if general:
        logger.warning(
            "Specialty template '%s' not found, falling back to 'general'",
            specialty,
        )
        return general

    raise ValueError(
        f"No template found for specialty '{specialty}' and no 'general' fallback available. "
        f"Available templates: {list(templates.keys())}"
    )


def list_available_templates() -> list[str]:
    """Return the keys of all loaded specialty templates."""
    return list(load_templates().keys())


# ── Completeness Score ────────────────────────────────────────────────────


# Section statuses that count toward "populated" for completeness purposes.
# ``populated`` is the Stage 1 / Stage 2 output. Keeping this as a set so
# the scorer can be extended without revisiting every call site.
_POPULATED_STATUSES = frozenset({"populated"})


def is_section_populated(section: Optional[NoteSection]) -> bool:
    """Return True iff ``section`` counts as populated for completeness.

    The honest definition has three legs:

    1. The status must be one of ``_POPULATED_STATUSES`` —
       ``pending_video``, ``not_captured``, and ``processing_failed``
       all fail this check.
    2. The section must have at least one claim. The pilot bug that
       motivated this lane (Marie's 2026-06-05 sessions) produced
       ``status="populated"`` sections with zero claims when the LLM
       was called against an empty transcript; the scorer used to
       count those as populated, which is dishonest.
    3. Every claim must carry a non-empty ``source_id``. The
       ``NoteClaim`` pydantic model already enforces this at
       deserialization time (``Field(..., min_length=1)``), but
       belt-and-braces here lets the scorer reject any claim that
       slipped past validation (e.g. an old DynamoDB row from a pre-
       constraint era).

    Returns False on a ``None`` section so the caller (the completeness
    loop) can pass ``note.get_section(...)`` straight in.
    """
    if section is None:
        return False
    if section.status not in _POPULATED_STATUSES:
        return False
    if not section.claims:
        return False
    return all(bool((c.source_id or "").strip()) for c in section.claims)


def calculate_completeness(note: Note, template: Template) -> float:
    """Calculate completeness = populated required sections / total required.

    ``populated`` is defined by :func:`is_section_populated` — see that
    docstring for the three-leg honest definition. Sections without
    ``required=True`` in the template are NOT in the denominator (the
    eval team can flip an optional section ``populated`` without
    inflating the completeness score).

    Returns 0.0 when the template has no required sections — a template
    that doesn't pin any required sections is effectively undefined for
    completeness purposes; surfacing 0.0 keeps the dashboard honest
    rather than the old behavior of returning 1.0 (which made an empty
    template look perfect).
    """
    required_sections = [s for s in template.sections if s.required]
    if not required_sections:
        return 0.0

    populated_count = sum(
        1
        for tmpl_section in required_sections
        if is_section_populated(note.get_section(tmpl_section.id))
    )
    return round(populated_count / len(required_sections), 4)


def compute_session_stats(
    note: Optional[Note], template: Template
) -> tuple[float, int, int, str]:
    """Roll the honest scorer up into the
    ``(completeness, populated, required, provider_used)`` tuple every
    admin endpoint surfaces.

    Single source of truth for the four denormalized stats so the list
    endpoint, the detail endpoint, and the recompute helper can never
    drift. ``None`` note → all zeros + empty provider; this matches the
    "session with no notes" contract from the lane brief (and what the
    admin endpoint already does in the empty-latest-note branch).
    """
    required = [s for s in template.sections if s.required]
    if note is None:
        return 0.0, 0, len(required), ""

    populated = sum(
        1
        for tmpl_section in required
        if is_section_populated(note.get_section(tmpl_section.id))
    )
    completeness = (
        round(populated / len(required), 4) if required else 0.0
    )
    return completeness, populated, len(required), note.provider_used or ""


# ── Prompt Building ───────────────────────────────────────────────────────

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
}


def build_stage1_user_prompt(
    transcript: Transcript,
    template: Template,
    encounter_context: Optional[str] = None,
    output_language: str = "en",
    participants: Optional[list[dict]] = None,
    prior_context_text: Optional[str] = None,
) -> str:
    """Build the user prompt for Stage 1 note generation.

    The system prompt is always NOTE_GENERATION_SYSTEM_PROMPT (set on the
    provider call). This function builds the user message containing the
    transcript content and the expected output schema.
    """
    # Build transcript text with segment references
    transcript_lines: list[str] = []
    for seg in transcript.segments:
        transcript_lines.append(
            f"[{seg.id}] ({seg.start_ms}ms\u2013{seg.end_ms}ms): {seg.text}"
        )
    transcript_text = "\n".join(transcript_lines)

    # Build sections specification from template
    sections_spec: list[dict[str, object]] = []
    for section in template.sections:
        sections_spec.append({
            "id": section.id,
            "title": section.title,
            "required": section.required,
            "description": section.description,
        })

    context_block = ""
    if encounter_context:
        context_block = (
            f"ENCOUNTER CONTEXT (provided by physician before session):\n"
            f"{encounter_context}\n\n"
        )

    # Prior-encounter context (#61, full slice). The rendered block is
    # already formatted by app.modules.longitudinal_context — empty
    # string when no prior was found (skip the heading entirely),
    # multi-line bullet list otherwise. Appended to the USER message
    # rather than the system prompt so the system prompt's strict
    # descriptive-mode rules stay unambiguous — see the
    # ``_PRIOR_CONTEXT_SYSTEM_SUFFIX`` rationale at the top of the
    # module.
    prior_context_section = ""
    if prior_context_text:
        prior_context_section = f"{prior_context_text}\n\n"

    language_block = ""
    if output_language != "en":
        lang_name = LANGUAGE_NAMES.get(output_language, output_language)
        language_block = (
            f"OUTPUT LANGUAGE: {lang_name}\n"
            f"Write ALL claim text and section content in {lang_name}. "
            f"Keep JSON keys, source_id references, and status values in English.\n\n"
        )

    # #275 — render via the shared helper so the anonymous-chip
    # (`name: null`) case is handled identically to the live provider
    # path (no KeyError on a missing name; role-only attribution for
    # unnamed speakers). The gate fires whenever ANY participant is
    # present — the enrolling clinician is an implicit second speaker, so
    # the old ``len(...) > 1`` test misfired for a single team member.
    participants_block = render_participants_block(participants)
    multi_participant = bool(participants)
    if multi_participant:
        attribution_instruction = (
            '- "text": the documented observation, attributed to the appropriate '
            "role when identifiable from context (e.g., \"Physician noted...\", "
            "\"Nurse reported...\", \"Resident observed...\"). "
            "When the speaker is ambiguous, use \"It was noted...\"\n"
        )
    else:
        attribution_instruction = (
            '- "text": the documented observation, prefixed with "Physician noted" '
            "or similar attribution\n"
        )

    # Per-specialty style snippet (Tier 2 / G). Layered on top of the
    # base system prompt's strict-rules section so the model picks up
    # specialty-appropriate terminology + structure preferences without
    # weakening descriptive mode.
    style_snippet = get_specialty_style(template.key)
    style_block = (
        f"STYLE GUIDANCE FOR {template.display_name}:\n{style_snippet}\n\n"
        if style_snippet else ""
    )

    # Few-shot examples (Tier 2 / E). One good worked example beats
    # three more rule sentences. Examples live at
    # templates/{key}.examples.json — empty for specialties without
    # examples authored yet (degrades to no examples block).
    few_shot_block = render_examples_block(get_few_shot_examples(template.key))

    prompt = (
        f"Specialty: {template.display_name}\n\n"
        f"{style_block}"
        f"{language_block}"
        f"{participants_block}"
        f"{context_block}"
        f"{prior_context_section}"
        f"{few_shot_block}"
        f"TRANSCRIPT:\n{transcript_text}\n\n"
        f"TEMPLATE SECTIONS:\n{json.dumps(sections_spec, indent=2)}\n\n"
        "Generate a structured clinical note from this transcript. "
        "For each section in the template, extract relevant claims from the "
        "transcript. Each claim must include:\n"
        '- "id": a unique claim ID (e.g. "claim_001")\n'
        f"{attribution_instruction}"
        '- "source_type": "transcript"\n'
        '- "source_id": the transcript segment ID (e.g. "seg_001")\n'
        '- "source_quote": the exact text from the transcript segment\n\n'
        "Choose the status for each section based on what the transcript contains:\n"
        '- "populated": the transcript directly describes content for this section '
        "(the physician narrates findings, observations, history, imaging review, "
        "wound assessment, etc. in their own words). Emit one claim per distinct "
        'observation with a transcript citation. ALWAYS use "populated" when the '
        "transcript has direct content for the section — do NOT defer transcript-"
        "described findings to pending_video.\n"
        '- "pending_video": the section depends on visual data AND the transcript '
        "contains no direct narration of the findings. Use this only when no "
        "transcript claim can be made and the section is expected to be filled by "
        "Stage 2 vision enrichment. Use an empty claims array.\n"
        '- "not_captured": the section has no relevant transcript content and is '
        "not expected to be filled by visual data either. Use an empty claims "
        "array.\n\n"
        "Return a JSON object with this exact structure:\n"
        "{\n"
        '  "sections": [\n'
        "    {\n"
        '      "id": "section_id",\n'
        '      "title": "Section Title",\n'
        '      "status": "populated|pending_video|not_captured",\n'
        '      "claims": [\n'
        "        {\n"
        '          "id": "claim_001",\n'
        '          "text": "Physician noted ...",\n'
        '          "source_type": "transcript",\n'
        '          "source_id": "seg_001",\n'
        '          "source_quote": "exact transcript text"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    return prompt


# ── Provider telemetry helper ────────────────────────────────────────────

async def _record_provider_usage(
    *,
    db: AsyncSession,
    provider_type: str,
    provider_name: str,
    operation: str,
    latency_ms: int,
    success: bool,
    session_id: str | None,
) -> None:
    """Best-effort write to ``provider_usage`` (issue #73).

    Swallows any DB error so a telemetry hiccup never alters the
    surrounding code path. Mirrors the wrapping pattern used at the
    alerts trigger sites (#76).

    OV-2 (#73): consumes the provider's ContextVar usage (read-once —
    consumed even on failure so stale tokens can never attach to a later
    call) and prices it via the shared core rate sheet.
    """
    usage = consume_call_usage()
    input_tokens = usage.input_tokens if usage else None
    output_tokens = usage.output_tokens if usage else None
    model_name = usage.model if usage else None
    cost_usd: float | None = None
    if usage is not None and success:
        micros = estimate_cost_usd_micros(
            provider_name, usage.model, usage.input_tokens, usage.output_tokens
        )
        cost_usd = micros / USD_MICROS_PER_DOLLAR
    try:
        await get_provider_usage_service().record(
            db,
            provider_type=provider_type,
            provider_name=provider_name,
            operation=operation,
            latency_ms=latency_ms,
            success=success,
            session_id=uuid.UUID(session_id) if session_id else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_name=model_name,
            cost_usd=cost_usd,
        )
    except Exception:  # noqa: BLE001 — telemetry is best-effort
        logger.warning(
            "provider_usage record failed: type=%s op=%s session=%s",
            provider_type,
            operation,
            session_id,
            exc_info=True,
        )


# ── Stage 1 Entry Guard (lane-backend/empty-transcript-guard) ──────────
#
# Calling a generative model with zero source material is a direct
# violation of CLAUDE.md §"The Single Most Important Constraint":
# "Describe only what was directly captured." An empty transcript means
# nothing was captured, so the only honest documentation is the absence
# of one. This guard short-circuits Stage 1 BEFORE any provider call
# when:
#
#   * the transcript record is missing (the transcription service never
#     persisted anything — usually because the audio upload bug Lane 2
#     is chasing), OR
#   * the transcript exists but has zero segments, OR
#   * the cumulative usable text across all segments is below
#     ``pipeline.min_transcript_char_threshold`` (default 20 — anything
#     shorter is silence or button-mash noise).
#
# The route handler catches ``EmptyTranscriptError`` and transitions
# the session to ``STAGE1_FAILED_NO_AUDIO`` instead of AWAITING_REVIEW.
# No note version is created, no provider call is made, no completeness
# score gets recorded — the broken session leaves zero hallucination
# surface area.

# Default keeps the guard active even when AppConfig is unreachable
# at start-up (the `.env` fallback path in appconfig_client returns the
# defaults). 20 chars ≈ "okay, that's good." — anything shorter is
# silence or button-mash noise.
DEFAULT_MIN_TRANSCRIPT_CHAR_THRESHOLD = 20


# Bounded enum strings for the audit event ``reason`` field. Strings
# rather than an Enum so the audit-log wire format stays string-comparable
# in DynamoDB queries; ``ALLOWED_AUDIT_KWARGS`` constrains the kwarg
# names, but the values are operator-readable text.
_REASON_TRANSCRIPT_EMPTY = "transcript_empty_or_missing"
_REASON_TRANSCRIPT_LOW = "transcript_too_short"


class EmptyTranscriptError(Exception):
    """Raised when the Stage 1 entry guard fires.

    ``reason`` is one of the bounded strings above. ``human_message``
    is the iOS-facing copy — descriptive, action-oriented, no
    PHI/transcript content. ``transcript_char_count`` is None for the
    empty/missing branch (no segments to count) and the cumulative
    integer count for the low-transcript branch.
    """

    def __init__(
        self,
        *,
        reason: str,
        human_message: str,
        transcript_char_count: Optional[int] = None,
    ) -> None:
        self.reason = reason
        self.human_message = human_message
        self.transcript_char_count = transcript_char_count
        super().__init__(f"[empty-transcript-guard] {reason}")


def _resolve_min_transcript_char_threshold() -> int:
    """Read ``pipeline.min_transcript_char_threshold`` from AppConfig.

    Wrapped in a try/except so any AppConfig hiccup degrades to the
    Pydantic default — Stage 1 must never crash because the threshold
    lookup hit a transient AWS error. The fallback matches the schema
    default (20) so behavior is byte-identical to a healthy AppConfig.
    """
    try:
        return int(get_config().pipeline.min_transcript_char_threshold)
    except Exception:  # noqa: BLE001 — defensive; never crash Stage 1
        logger.warning(
            "Failed to read pipeline.min_transcript_char_threshold from "
            "AppConfig; falling back to default %d",
            DEFAULT_MIN_TRANSCRIPT_CHAR_THRESHOLD,
            exc_info=True,
        )
        return DEFAULT_MIN_TRANSCRIPT_CHAR_THRESHOLD


async def _enforce_transcript_guard(
    transcript: Optional[Transcript], session_id: str
) -> None:
    """Short-circuit Stage 1 when there's no usable transcript.

    Writes the STAGE1_SKIPPED_* audit event and raises
    ``EmptyTranscriptError``. Never returns a value — successful guard
    pass is silent. The audit row carries NO transcript content: only
    a bounded reason string and (on the low branch) a small char count.
    """
    audit = get_audit_log_service()

    if transcript is None or not transcript.segments:
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.STAGE1_SKIPPED_NO_TRANSCRIPT,
            reason=_REASON_TRANSCRIPT_EMPTY,
        )
        raise EmptyTranscriptError(
            reason=_REASON_TRANSCRIPT_EMPTY,
            human_message=(
                "No audio was transcribed for this session. Check your "
                "microphone and re-record."
            ),
        )

    # Cumulative usable-character count across all segments. ``s.text``
    # is the LLM-input text; stripping whitespace catches segments that
    # carry only spaces (some transcription providers emit those for
    # silence frames). NO transcript content leaks past this scope.
    total_text_len = sum(len((s.text or "").strip()) for s in transcript.segments)
    threshold = _resolve_min_transcript_char_threshold()
    if total_text_len < threshold:
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.STAGE1_SKIPPED_LOW_TRANSCRIPT,
            reason=_REASON_TRANSCRIPT_LOW,
            transcript_char_count=total_text_len,
        )
        raise EmptyTranscriptError(
            reason=_REASON_TRANSCRIPT_LOW,
            human_message=(
                "Recording was too short to produce a note. Please re-record."
            ),
            transcript_char_count=total_text_len,
        )


# ── Stage 1 template resolution (#318 / B3) ──────────────────────────────


async def _resolve_stage1_template(
    *,
    template_key: Optional[str],
    specialty: str,
    custom_template_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> Template:
    """Resolve the ``Template`` to use for Stage 1.

    When the session snapshotted a ``custom_template_id`` (the chosen
    context bound a custom ``template_ref``, #318 / B3), load that row's
    content and validate it against the ``Template`` Pydantic schema
    before use. Any defensive failure — the row was deleted after the
    snapshot, the lookup errored, or the stored content no longer parses
    as a ``Template`` — degrades to the built-in / specialty path so
    Stage 1 never crashes over a stale custom binding.

    When ``custom_template_id`` is ``None`` the resolution is
    byte-for-byte the pre-#318 behaviour: ``get_template(template_key or
    specialty)``. The built-in / None paths never touch the
    custom_templates table.
    """
    if custom_template_id is None:
        return get_template(template_key or specialty)

    # Lazy import — keep note_gen free of an import-time dependency on the
    # custom_templates module (mirrors the session-service lazy imports).
    from app.modules.custom_templates.service import get_by_id

    try:
        row = await get_by_id(custom_template_id, db)
    except Exception:  # noqa: BLE001 — never crash Stage 1 over a lookup
        logger.warning(
            "Custom template load failed (custom_template_id=%s); falling "
            "back to specialty default",
            custom_template_id,
            exc_info=True,
        )
        return get_template(template_key or specialty)

    if row is None:
        logger.info(
            "Custom template %s not found at Stage 1 (deleted after "
            "snapshot?); falling back to %s",
            custom_template_id,
            template_key or specialty,
        )
        return get_template(template_key or specialty)

    try:
        # Validate against the Template schema before use. The content was
        # validated on every write, but a row from a pre-constraint era
        # (or a future schema change) shouldn't be trusted blindly into
        # the pipeline.
        return Template.model_validate_json(row.content)
    except ValidationError:
        logger.error(
            "Custom template %s content no longer validates against the "
            "Template schema; falling back to specialty default",
            custom_template_id,
        )
        return get_template(template_key or specialty)


# ── Stage 1 Note Generation ──────────────────────────────────────────────


async def generate_stage1_note(
    transcript: Transcript,
    specialty: str,
    session_id: str,
    db: AsyncSession,
    provider_override: Optional[str] = None,
    output_language: str = "en",
    template_key: Optional[str] = None,
    custom_template_id: Optional[uuid.UUID] = None,
    participants: Optional[list[dict]] = None,
) -> Note:
    """Generate a Stage 1 note from a transcript.

    ``template_key`` is the per-session SNAPSHOT of the chosen
    Visit Type → Context → Template selection (#314 / B2). When set it
    drives which template's sections get populated; when ``None`` the
    session ``specialty`` default is used — byte-for-byte the pre-#314
    behaviour. ``specialty`` is still threaded through for completeness-
    score continuity and stored on the note + version row.

    ``custom_template_id`` is the per-session SNAPSHOT of a CUSTOM
    template the chosen context bound (#318 / B3). When set, that custom
    template's content is loaded + validated against the ``Template``
    schema and used for Stage 1; a stale snapshot (row deleted, or
    content that no longer validates) degrades defensively to the
    built-in / specialty path. When ``None`` the resolution is exactly
    ``get_template(template_key or specialty)`` — byte-for-byte unchanged.

    Pipeline:
    1. Load the template (custom snapshot → ``template_key`` snapshot →
       specialty)
    2. Select the system prompt — the calling physician's saved user
       prompt when present, the CLAUDE.md default otherwise
       (AI-PROMPTS-B replacement semantics)
    3. Load prior-encounter context for the same clinician + patient
       identifier (#61, full slice). Skipped when no identifier set.
    4. Call the active NoteGenerationProvider via the registry
    5. Calculate completeness score
    6. Create version record in the database

    Returns the generated Note with completeness score and version.

    Raises:
        EmptyTranscriptError: when the transcript is empty / missing /
            below ``pipeline.min_transcript_char_threshold``. The provider
            is NOT called in this branch — CLAUDE.md §"The Single Most
            Important Constraint" forbids generative calls with zero
            source material. The audit trail records the STAGE1_SKIPPED_*
            event with a bounded reason string before the exception is
            raised; the route handler catches it and transitions the
            session to ``STAGE1_FAILED_NO_AUDIO``.
    """
    # ── Stage 1 entry guard (lane-backend/empty-transcript-guard) ────
    # Fires BEFORE template loading + registry lookup so we don't pay
    # those costs for a session we already know we won't process.
    await _enforce_transcript_guard(transcript, session_id)

    # #275 — encounter participants drive role/name attribution in the
    # prompt. The caller (transcription route) passes them in already
    # deserialized; for any other caller / tests that don't, fall back to
    # loading the snapshot off the session row so attribution is never
    # silently dropped.
    if participants is None:
        participants = await _load_session_participants(session_id, db)

    # #314 / #318 — resolve the Stage-1 template: a custom snapshot wins
    # when present (load + validate its content), else the snapshotted
    # built-in template_key, else the session specialty exactly as before.
    template = await _resolve_stage1_template(
        template_key=template_key,
        specialty=specialty,
        custom_template_id=custom_template_id,
        db=db,
    )
    registry = get_registry()

    if provider_override:
        provider = registry.get_note_provider(override=provider_override)
    else:
        provider = registry.get_note_provider_with_fallback()

    logger.info(
        "Generating Stage 1 note: session=%s specialty=%s template=%s provider=%s",
        session_id,
        specialty,
        template.key,
        type(provider).__name__,
    )

    # AI-PROMPTS-B — select the prompt at call time. When the calling
    # physician has saved a user prompt it replaces the base; otherwise
    # the registry default is used. Sessions without a resolvable
    # clinician_id always use the default (defensive — shouldn't happen
    # in production but the helper handles it).
    system_prompt = await assemble_prompt_for_session(
        "note_generation", session_id, db
    )

    # #61, full slice — load prior-encounter context for this clinician
    # + patient identifier. Returns None when no identifier is set on
    # the session (cold-start signal — the prior-context branch is
    # skipped entirely). When non-None, the rendered block goes into
    # the USER message and a descriptive-mode reinforcement sentence
    # gets concatenated onto the SYSTEM prompt at call time (the base
    # registry prompt itself is never mutated; see
    # ``_PRIOR_CONTEXT_SYSTEM_SUFFIX`` rationale at the top of this
    # module).
    prior_block, prior_context_text = await _load_prior_context_block(
        session_id, db
    )
    if prior_context_text:
        system_prompt = system_prompt + _PRIOR_CONTEXT_SYSTEM_SUFFIX

    # Wrap the registry call to capture per-call telemetry (issue #73).
    # Both the success and failure paths record so dashboards can show
    # failure / fallback rates accurately. Telemetry is best-effort —
    # a writer hiccup never alters the surrounding code path.
    _usage_started = time.monotonic()
    try:
        note = await provider.generate_note(
            transcript,
            template,
            stage=1,
            output_language=output_language,
            system_prompt=system_prompt,
            prior_context_text=prior_context_text or None,
            participants=participants or None,
        )
        await _record_provider_usage(
            db=db,
            provider_type="note_generation",
            provider_name=getattr(note, "provider_used", "unknown"),
            operation="generate_note",
            latency_ms=int((time.monotonic() - _usage_started) * 1000),
            success=True,
            session_id=session_id,
        )
    except Exception:
        await _record_provider_usage(
            db=db,
            provider_type="note_generation",
            provider_name=type(provider).__name__,
            operation="generate_note",
            latency_ms=int((time.monotonic() - _usage_started) * 1000),
            success=False,
            session_id=session_id,
        )
        raise

    note.session_id = session_id
    note.stage = 1
    note.specialty = specialty

    # Self-critique pass — second LLM call audits the just-generated
    # note for unanchored claims and section-status mistakes. Mutates
    # ``note`` in place; best-effort, no-op on any failure. Runs in
    # series after generation (~1-2s typical) so the persisted v1 is
    # the cleaned-up version, not the raw output.
    await critique_note(note, transcript)

    # Re-score after critique — dropping unanchored claims or flipping
    # populated -> not_captured changes the completeness denominator.
    note.completeness_score = round(calculate_completeness(note, template), 4)

    # Attach the slim count-only prior-context summary (#61). Carries
    # NO PHI — only the integer count of prior encounters the model
    # actually consumed and the date of the most recent one. iOS badge
    # + web chip read ``encounters_referenced > 0`` to decide whether
    # to surface the "Context-aware" affordance.
    note.prior_context_used = _build_prior_context_used(prior_block)

    # Audit row — count + date only, NEVER the identifier value, the
    # prior session ids, or any clinical content. The whitelist in
    # app.core.audit_events.ALLOWED_AUDIT_KWARGS pins the exact key
    # set; an accidental new kwarg here would fail strict mode in
    # tests immediately (see backend/tests/conftest.py).
    await _emit_longitudinal_context_audit(
        session_id=session_id, db=db, prior_block=prior_block
    )

    logger.info(
        "Stage 1 note generated: session=%s provider=%s completeness=%.2f sections=%d",
        session_id,
        note.provider_used,
        note.completeness_score,
        len(note.sections),
    )

    await create_note_version(session_id, note, db)

    return note


async def _load_session_participants(
    session_id: str, db: AsyncSession
) -> list[dict]:
    """Load the encounter participant snapshot off the session row (#275).

    Defensive on every axis — a bad ``session_id``, a missing row, a NULL
    or malformed ``participants_json``, or anything that isn't a JSON list
    degrades to ``[]`` so Stage 1 never crashes over participant
    attribution. Returns the raw stored dicts ({name, role, source,
    is_persistent}); the renderer guards the anonymous-chip (`name: null`)
    case itself.
    """
    try:
        sid = uuid.UUID(str(session_id))
    except (ValueError, TypeError):
        return []
    try:
        row = (
            await db.execute(
                select(SessionModel.participants_json).where(
                    SessionModel.id == sid
                )
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — never crash Stage 1 over a lookup
        logger.warning(
            "Failed to load participants for session=%s", session_id,
            exc_info=True,
        )
        return []
    if not row:
        return []
    try:
        parsed = json.loads(row)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


# ── Prior-context wiring helpers ────────────────────────────────────────

async def _load_prior_context_block(
    session_id: str, db: AsyncSession
) -> tuple[Optional[PriorContextBlock], str]:
    """Resolve the session's clinician + identifier and load prior
    context.

    Returns ``(block, rendered_text)``:
      * ``block`` is the raw :class:`PriorContextBlock` (or ``None``
        when no identifier is set or the session lookup fails).
        ``_build_prior_context_used`` consumes this to populate
        ``note.prior_context_used``; the audit emitter also reads it.
      * ``rendered_text`` is the deterministic block from
        :func:`render_prior_context_block` — empty string when there's
        nothing to render. Lets the caller decide unconditionally
        whether to inject it.

    Any DB error / lookup failure degrades to ``(None, "")`` — Stage 1
    must never fail because the prior-context branch hiccuped.
    """
    try:
        result = await db.execute(
            select(SessionModel.clinician_id, SessionModel.external_reference_id_encrypted).where(
                SessionModel.id == uuid.UUID(session_id)
            )
        )
        row = result.one_or_none()
    except Exception:  # noqa: BLE001 — defensive; never crash Stage 1
        logger.warning(
            "Prior-context lookup skipped — session row fetch failed (session=%s)",
            session_id,
            exc_info=True,
        )
        return None, ""

    if row is None or row.external_reference_id_encrypted is None:
        return None, ""

    # We need plaintext to hash. Direct decrypt here rather than
    # re-walking the model layer; this is the only site outside the
    # API surface that needs to read the identifier, and pulling in a
    # helper just for this would be DRY-overkill.
    try:
        from app.core.kms_encryption import decrypt_str

        plaintext = decrypt_str(bytes(row.external_reference_id_encrypted))
    except Exception:  # noqa: BLE001 — decrypt failure → no context, log
        logger.warning(
            "Prior-context lookup skipped — identifier decrypt failed (session=%s)",
            session_id,
        )
        return None, ""

    try:
        block = await get_prior_context(
            clinician_id=row.clinician_id,
            patient_identifier=plaintext,
            current_session_id=uuid.UUID(session_id),
            db=db,
        )
    except Exception:  # noqa: BLE001 — same defensive contract
        logger.warning(
            "Prior-context lookup failed (session=%s)", session_id, exc_info=True
        )
        return None, ""

    if block is None:
        return None, ""
    return block, render_prior_context_block(block)


def _build_prior_context_used(
    prior_block: Optional[PriorContextBlock],
) -> Optional[PriorContextUsedSummary]:
    """Roll the loaded block into the slim wire summary that gets
    attached to ``Note.prior_context_used``.

    Returns ``None`` when no block was loaded (cold-start), or when
    the block was loaded but had zero encounters — keeping the wire
    null in both "we didn't look" and "we looked but found nothing"
    avoids the iOS / web badges needing to distinguish the two; if a
    physician ever wants that surfaced separately we promote the
    "looked, found zero" branch to a non-None summary with
    ``encounters_referenced=0``.
    """
    if prior_block is None or not prior_block.encounters:
        return None
    most_recent = prior_block.encounters[0]
    return PriorContextUsedSummary(
        encounters_referenced=len(prior_block.encounters),
        last_encounter_date=most_recent.date.isoformat(),
    )


async def _emit_longitudinal_context_audit(
    *,
    session_id: str,
    db: AsyncSession,
    prior_block: Optional[PriorContextBlock],
) -> None:
    """Write the LONGITUDINAL_CONTEXT_LOADED audit event when prior
    context was actually consumed.

    Keys are exactly ``{actor_id, current_session_id, encounters_count,
    last_encounter_date}`` — the whitelist in
    ``ALLOWED_AUDIT_KWARGS`` is pinned to this set. No identifier
    value, no prior session ids, no clinical content. ``actor_id`` is
    the session's clinician (we look it up rather than threading it
    through — Stage 1 is server-initiated and there isn't always a
    request-bound user in scope at this layer).
    """
    if prior_block is None or not prior_block.encounters:
        # No event when nothing was loaded — the absence of a row IS
        # the signal. Forcing an "empty load" event for every cold-
        # start session would dilute the audit-log signal.
        return
    try:
        result = await db.execute(
            select(SessionModel.clinician_id).where(
                SessionModel.id == uuid.UUID(session_id)
            )
        )
        clinician_id = result.scalar_one_or_none()
    except Exception:  # noqa: BLE001 — never crash Stage 1 over audit
        logger.warning(
            "LONGITUDINAL_CONTEXT_LOADED audit skipped — clinician lookup "
            "failed (session=%s)",
            session_id,
            exc_info=True,
        )
        return

    if clinician_id is None:
        return

    most_recent = prior_block.encounters[0]
    try:
        await get_audit_log_service().write_event(
            session_id=session_id,
            event_type=AuditEventType.LONGITUDINAL_CONTEXT_LOADED,
            actor_id=str(clinician_id),
            current_session_id=session_id,
            encounters_count=len(prior_block.encounters),
            last_encounter_date=most_recent.date.isoformat(),
        )
    except Exception:  # noqa: BLE001 — audit is best-effort
        logger.warning(
            "LONGITUDINAL_CONTEXT_LOADED audit write failed (session=%s)",
            session_id,
            exc_info=True,
        )


# ── Note Versioning ───────────────────────────────────────────────────────


async def _emit_session_stats_recomputed(
    *,
    session_id: str,
    trigger: str,
    completeness_score: float,
    sections_populated: int,
    sections_required: int,
    previous_completeness_score: float,
) -> None:
    """Write the SESSION_STATS_RECOMPUTED audit row when the recompute
    actually changed the headline completeness number.

    No-op when nothing changed — the audit log is append-only and we
    don't want a row for every Stage 2 frame ingestion that didn't
    move the needle. ``trigger`` is a small bounded label
    ("create_note_version" today; future call sites add their own).
    PHI-safe: only the roll-up counts cross into the audit row.
    """
    # Compare at the persisted precision (4 dp) so floating-point hiccups
    # in the recompute don't trip a write.
    if round(completeness_score, 4) == round(previous_completeness_score, 4):
        return
    try:
        await get_audit_log_service().write_event(
            session_id=session_id,
            event_type=AuditEventType.SESSION_STATS_RECOMPUTED,
            trigger=trigger,
            sections_populated=sections_populated,
            sections_required=sections_required,
            completeness_score=round(completeness_score, 4),
        )
    except Exception:  # noqa: BLE001 — audit is best-effort
        logger.warning(
            "SESSION_STATS_RECOMPUTED audit write failed (session=%s)",
            session_id,
            exc_info=True,
        )


async def create_note_version(
    session_id: str,
    note: Note,
    db: AsyncSession,
    *,
    recompute_completeness: bool = True,
    stats_trigger: str = "create_note_version",
) -> NoteVersionModel:
    """Create a new immutable note version record.

    Every edit creates a new version. No version is ever deleted.

    ``recompute_completeness`` (default True) re-derives the score
    from the in-memory ``note.sections`` + the specialty template
    every time a version is written. Before this lane, edit_note /
    resolve_conflict / vision / screen all called us with stale
    in-memory ``note.completeness_score`` values; the persisted score
    drifted from what the honest scorer would say given the same
    sections. Recomputing centrally is the single source of truth.

    ``stats_trigger`` flows into the SESSION_STATS_RECOMPUTED audit
    row's ``trigger`` field — see ``_emit_session_stats_recomputed``.
    """
    result = await db.execute(
        select(func.max(NoteVersionModel.version)).where(
            NoteVersionModel.session_id == uuid.UUID(session_id)
        )
    )
    max_version = result.scalar() or 0
    next_version = max_version + 1

    note.version = next_version

    # lane-backend/empty-transcript-guard: recompute the persisted
    # completeness so every CUD path (edit, conflict resolve, vision
    # merge, screen inject) ends up with an honest score. We swallow
    # template-load failures defensively — Stage 1 won't reach here
    # without a valid template, but custom-template rows from the
    # eval team could in theory have a stale ``specialty`` key.
    previous_score = float(note.completeness_score or 0.0)
    sections_populated = 0
    sections_required = 0
    if recompute_completeness:
        try:
            template = get_template(note.specialty)
        except Exception:  # noqa: BLE001 — never crash a version write
            logger.warning(
                "Completeness recompute skipped — template lookup failed "
                "(session=%s specialty=%s)",
                session_id,
                note.specialty,
            )
            template = None
        if template is not None:
            (
                completeness,
                sections_populated,
                sections_required,
                _provider,
            ) = compute_session_stats(note, template)
            note.completeness_score = round(completeness, 4)

    version_record = NoteVersionModel(
        session_id=uuid.UUID(session_id),
        version=next_version,
        stage=note.stage,
        provider_used=note.provider_used,
        specialty=note.specialty,
        completeness_score=note.completeness_score,
        content=json.dumps(note.model_dump(), default=str),
        is_approved=False,
    )
    db.add(version_record)
    await db.flush()

    logger.info(
        "Note version created: session=%s version=%d stage=%d "
        "completeness=%.4f populated=%d required=%d",
        session_id,
        next_version,
        note.stage,
        note.completeness_score,
        sections_populated,
        sections_required,
    )

    # Only emit the recompute audit on subsequent versions — version 1
    # is the initial creation and STAGE1_DELIVERED already captures
    # that signal. Versions ≥ 2 represent a real edit / merge / inject
    # path where the recompute genuinely changes the dashboard story.
    if recompute_completeness and next_version > 1:
        await _emit_session_stats_recomputed(
            session_id=session_id,
            trigger=stats_trigger,
            completeness_score=float(note.completeness_score),
            sections_populated=sections_populated,
            sections_required=sections_required,
            previous_completeness_score=previous_score,
        )

    return version_record


async def get_latest_note(
    session_id: str,
    db: AsyncSession,
) -> Optional[Note]:
    """Retrieve the latest note version for a session.

    The clinician always sees and edits the latest version. Previous
    versions are retained silently in the audit trail.
    """
    version_record = await note_repo.get_latest_version(db, session_id)
    return _deserialize_note(version_record) if version_record else None


async def get_note_by_stage(
    session_id: str,
    stage: int,
    db: AsyncSession,
) -> Optional[Note]:
    """Retrieve the latest note version for a specific stage."""
    version_record = await note_repo.get_latest_version(db, session_id, stage=stage)
    return _deserialize_note(version_record) if version_record else None


async def approve_note(
    session_id: str,
    db: AsyncSession,
) -> Note:
    """Approve the latest note version -- marks it as vFinal.

    Creates a new approved version record. Returns the approved Note.
    Raises ValueError if no note exists for the session.
    """
    version_record = await note_repo.get_latest_version(db, session_id)

    if not version_record:
        raise ValueError(f"No note found for session {session_id}")

    if version_record.is_approved:
        # Already approved -- return existing note
        return _deserialize_note(version_record)

    version_record.is_approved = True
    await db.flush()

    note = _deserialize_note(version_record)
    logger.info(
        "Note approved: session=%s version=%d stage=%d (vFinal)",
        session_id,
        version_record.version,
        note.stage,
    )

    return note


async def edit_note(
    session_id: str,
    section_edits: dict[str, str],
    db: AsyncSession,
) -> Note:
    """Apply physician edits to the latest note version.

    Creates a new immutable version -- the original is never modified.

    Args:
        session_id: The session owning the note.
        section_edits: Dict mapping section_id to new claim text.
            Each key is a section id (e.g. "physical_exam"), and the
            value is the updated text for the first claim in that section.
            If the section has no claims, a new claim is created.
        db: Async database session.

    Returns:
        The updated Note with incremented version number.

    Raises:
        ValueError: If no note exists for the session.
    """
    latest = await get_latest_note(session_id, db)
    if not latest:
        raise ValueError(f"No note found for session {session_id}")

    edited_note = latest.model_copy(deep=True)

    for section_id, new_text in section_edits.items():
        section = edited_note.get_section(section_id)
        if section is None:
            logger.warning(
                "Edit skipped -- section '%s' not found in note for session=%s",
                section_id,
                session_id,
            )
            continue

        if section.claims:
            # Preserve provenance: keep the original source_type and source_id,
            # mark physician_edited=True, and stash the pre-edit text on the
            # first edit only. Re-editing a previously edited claim leaves
            # `original_text` pointing at the original (Stage 1) text, which
            # is what the audit trail wants.
            claim = section.claims[0]
            if not claim.physician_edited:
                claim.original_text = claim.text
                claim.physician_edited = True
            claim.text = new_text
        else:
            # Net-new physician claim — no Stage 1 anchor exists, so the
            # source provenance is the edit itself.
            section.claims.append(
                NoteClaim(
                    id=f"pclaim_{uuid.uuid4().hex[:8]}",
                    text=new_text,
                    source_type="physician_edit",
                    source_id=f"pedit_{section_id}",
                    source_quote="",
                    physician_edited=True,
                )
            )
            section.status = "populated"

    await create_note_version(
        session_id,
        edited_note,
        db,
        stats_trigger="edit_note",
    )

    logger.info(
        "Note edited: session=%s new_version=%d sections_edited=%s",
        session_id,
        edited_note.version,
        list(section_edits.keys()),
    )

    return edited_note


CONFLICT_RESOLUTION_ACTIONS = ("accept_visual", "reject_visual", "edit")


async def resolve_conflict(
    session_id: str,
    claim_id: str,
    action: str,
    resolution_text: str | None,
    db: AsyncSession,
) -> Note:
    """Resolve a single Stage 2 visual conflict, writing a new note version.

    Actions:
        - "accept_visual": keep the visual claim as-is; mark it physician_edited
          so the approval gate stops blocking. Use when the visual evidence is
          right and the audio narration was wrong/incomplete.
        - "reject_visual": remove the conflict claim from the section. Use when
          the audio was correct and the visual frame was misleading.
        - "edit": replace the claim text with `resolution_text`. Original text
          is stashed; physician_edited is True.

    Each action writes a new immutable note version; the original conflict
    claim is preserved in version history.

    Raises:
        ValueError: no note for session, claim not found, unknown action, or
            "edit" called without resolution_text.
    """
    if action not in CONFLICT_RESOLUTION_ACTIONS:
        raise ValueError(f"Unknown resolution action: {action!r}")
    if action == "edit" and not (resolution_text and resolution_text.strip()):
        raise ValueError("'edit' action requires non-empty resolution_text")

    latest = await get_latest_note(session_id, db)
    if not latest:
        raise ValueError(f"No note found for session {session_id}")

    updated = latest.model_copy(deep=True)

    target = next(
        ((section, claim) for section in updated.sections for claim in section.claims if claim.id == claim_id),
        None,
    )
    if target is None:
        raise ValueError(f"Claim {claim_id} not found in latest note for session {session_id}")
    target_section, target_claim = target

    if action == "accept_visual":
        if not target_claim.physician_edited:
            target_claim.original_text = target_claim.text
        target_claim.physician_edited = True
    elif action == "reject_visual":
        target_section.claims = [c for c in target_section.claims if c.id != claim_id]
    else:  # action == "edit" — validated above, resolution_text is non-empty
        if not target_claim.physician_edited:
            target_claim.original_text = target_claim.text
        target_claim.text = resolution_text or ""
        target_claim.physician_edited = True

    await create_note_version(
        session_id,
        updated,
        db,
        stats_trigger="resolve_conflict",
    )

    logger.info(
        "Conflict resolved: session=%s claim=%s action=%s new_version=%d",
        session_id,
        claim_id,
        action,
        updated.version,
    )

    return updated


async def is_note_approved(session_id: str, db: AsyncSession) -> bool:
    """Check whether any note version for this session has been approved."""
    result = await db.execute(
        select(NoteVersionModel.id)
        .where(
            NoteVersionModel.session_id == uuid.UUID(session_id),
            NoteVersionModel.is_approved.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_all_versions(
    session_id: str,
    db: AsyncSession,
) -> list[NoteVersionModel]:
    """Get all note versions for a session, ordered by version number."""
    return await note_repo.get_all_versions(db, session_id)


# ── Deserialization ───────────────────────────────────────────────────────

def _deserialize_note(version_record: NoteVersionModel) -> Note:
    """Deserialize a NoteVersionModel's JSON content into a Note."""
    content = json.loads(version_record.content)
    return Note(**content)
