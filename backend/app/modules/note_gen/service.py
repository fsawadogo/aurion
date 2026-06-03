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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import NoteVersionModel, SessionModel
from app.core.types import Note, NoteClaim, Template, Transcript
from app.modules.config.provider_registry import get_registry
from app.modules.note_gen import repository as note_repo
from app.modules.note_gen.critique import critique_note
from app.modules.note_gen.few_shot import get_few_shot_examples, render_examples_block
from app.modules.note_gen.specialty_style import get_specialty_style
from app.modules.prompts import assemble_prompt
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

    Falls back to 'general' if the requested specialty is not found.
    Raises ValueError if no template is available at all.
    """
    templates = load_templates()

    template = templates.get(specialty)
    if template:
        return template

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

def calculate_completeness(note: Note, template: Template) -> float:
    """Calculate completeness = populated required sections / total required sections.

    A section is considered populated if its status is 'populated' and it
    has at least one claim.
    """
    required_sections = [s for s in template.sections if s.required]
    if not required_sections:
        return 1.0

    populated_count = 0
    for tmpl_section in required_sections:
        note_section = note.get_section(tmpl_section.id)
        if (
            note_section
            and note_section.status == "populated"
            and len(note_section.claims) > 0
        ):
            populated_count += 1

    return round(populated_count / len(required_sections), 4)


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

    language_block = ""
    if output_language != "en":
        lang_name = LANGUAGE_NAMES.get(output_language, output_language)
        language_block = (
            f"OUTPUT LANGUAGE: {lang_name}\n"
            f"Write ALL claim text and section content in {lang_name}. "
            f"Keep JSON keys, source_id references, and status values in English.\n\n"
        )

    participants_block = ""
    multi_participant = participants and len(participants) > 1
    if multi_participant:
        roles_list = "\n".join(
            f"- {p['name']} ({p['role'].replace('_', ' ').title()})"
            for p in participants
        )
        participants_block = (
            f"ENCOUNTER PARTICIPANTS:\n{roles_list}\n\n"
            "Since multiple people are present, attribute statements to the "
            "appropriate role when identifiable from context (e.g., "
            "'Nurse noted...', 'Resident reported...'). When the speaker is "
            "ambiguous, use 'It was noted...' rather than attributing to a "
            "specific person.\n\n"
        )

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
    """
    try:
        await get_provider_usage_service().record(
            db,
            provider_type=provider_type,
            provider_name=provider_name,
            operation=operation,
            latency_ms=latency_ms,
            success=success,
            session_id=uuid.UUID(session_id) if session_id else None,
        )
    except Exception:  # noqa: BLE001 — telemetry is best-effort
        logger.warning(
            "provider_usage record failed: type=%s op=%s session=%s",
            provider_type,
            operation,
            session_id,
            exc_info=True,
        )


# ── Stage 1 Note Generation ──────────────────────────────────────────────


async def _resolve_session_clinician(
    session_id: str, db: AsyncSession
) -> Optional[uuid.UUID]:
    """Look up the session's ``clinician_id``.

    Threads the owner into per-physician prompt assembly (AI-PROMPTS-B).
    Returns ``None`` when the session isn't found — the caller falls
    back to the base prompt so a missing row never blocks Stage 1.
    """
    try:
        sid = uuid.UUID(session_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        select(SessionModel.clinician_id).where(SessionModel.id == sid)
    )
    return result.scalar_one_or_none()


async def generate_stage1_note(
    transcript: Transcript,
    specialty: str,
    session_id: str,
    db: AsyncSession,
    provider_override: Optional[str] = None,
    output_language: str = "en",
) -> Note:
    """Generate a Stage 1 note from a transcript.

    Pipeline:
    1. Load the specialty template
    2. Build the prompt using the exact system prompt from CLAUDE.md +
       the calling physician's per-physician overlay (AI-PROMPTS-B)
    3. Call the active NoteGenerationProvider via the registry
    4. Calculate completeness score
    5. Create version record in the database

    Returns the generated Note with completeness score and version.
    """
    template = get_template(specialty)
    registry = get_registry()

    if provider_override:
        provider = registry.get_note_provider(override=provider_override)
    else:
        provider = registry.get_note_provider_with_fallback()

    logger.info(
        "Generating Stage 1 note: session=%s specialty=%s provider=%s",
        session_id,
        specialty,
        type(provider).__name__,
    )

    # AI-PROMPTS-B — assemble the (base + per-physician overlay) prompt
    # at call time. The owner is the session's clinician_id; if the
    # lookup misses, we fall back to the base prompt so a missing
    # session row never blocks Stage 1.
    clinician_id = await _resolve_session_clinician(session_id, db)
    system_prompt: Optional[str] = None
    if clinician_id is not None:
        system_prompt = await assemble_prompt(
            "note_generation", clinician_id, db
        )

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

    logger.info(
        "Stage 1 note generated: session=%s provider=%s completeness=%.2f sections=%d",
        session_id,
        note.provider_used,
        note.completeness_score,
        len(note.sections),
    )

    await create_note_version(session_id, note, db)

    return note


# ── Note Versioning ───────────────────────────────────────────────────────

async def create_note_version(
    session_id: str,
    note: Note,
    db: AsyncSession,
) -> NoteVersionModel:
    """Create a new immutable note version record.

    Every edit creates a new version. No version is ever deleted.
    """
    result = await db.execute(
        select(func.max(NoteVersionModel.version)).where(
            NoteVersionModel.session_id == uuid.UUID(session_id)
        )
    )
    max_version = result.scalar() or 0
    next_version = max_version + 1

    note.version = next_version

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
        "Note version created: session=%s version=%d stage=%d",
        session_id,
        next_version,
        note.stage,
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

    await create_note_version(session_id, edited_note, db)

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

    await create_note_version(session_id, updated, db)

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
