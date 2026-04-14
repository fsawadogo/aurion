"""Stage 1 note generation service.

Loads specialty templates from JSON files, builds prompts with the exact
descriptive-mode system prompt, calls the active NoteGenerationProvider via
the registry, calculates completeness scores, and manages note versioning.

No business logic in API route handlers -- routes call these functions only.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import NoteVersionModel
from app.core.types import Note, NoteSection, NoteClaim, Template, TemplateSection, Transcript
from app.modules.config.provider_registry import get_registry

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

def build_stage1_user_prompt(transcript: Transcript, template: Template) -> str:
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

    prompt = (
        f"Specialty: {template.display_name}\n\n"
        f"TRANSCRIPT:\n{transcript_text}\n\n"
        f"TEMPLATE SECTIONS:\n{json.dumps(sections_spec, indent=2)}\n\n"
        "Generate a structured clinical note from this transcript. "
        "For each section in the template, extract relevant claims from the "
        "transcript. Each claim must include:\n"
        '- "id": a unique claim ID (e.g. "claim_001")\n'
        '- "text": the documented observation, prefixed with "Physician noted" '
        "or similar attribution\n"
        '- "source_type": "transcript"\n'
        '- "source_id": the transcript segment ID (e.g. "seg_001")\n'
        '- "source_quote": the exact text from the transcript segment\n\n'
        "If a section has no relevant transcript content, set its status to "
        '"not_captured" with an empty claims array.\n'
        'If a section has content, set its status to "populated".\n'
        "For sections that could benefit from visual data (physical exam, imaging, "
        'wound assessment), set status to "pending_video" if transcript content '
        "is present but visual enrichment is expected.\n\n"
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


# ── Stage 1 Note Generation ──────────────────────────────────────────────

async def generate_stage1_note(
    transcript: Transcript,
    specialty: str,
    session_id: str,
    db: AsyncSession,
    provider_override: Optional[str] = None,
) -> Note:
    """Generate a Stage 1 note from a transcript.

    Pipeline:
    1. Load the specialty template
    2. Build the prompt using the exact system prompt from CLAUDE.md
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

    note = await provider.generate_note(transcript, template, stage=1)

    note.session_id = session_id
    note.stage = 1
    note.specialty = specialty

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
    result = await db.execute(
        select(NoteVersionModel)
        .where(NoteVersionModel.session_id == uuid.UUID(session_id))
        .order_by(NoteVersionModel.version.desc())
        .limit(1)
    )
    version_record = result.scalar_one_or_none()
    if not version_record:
        return None

    return _deserialize_note(version_record)


async def get_note_by_stage(
    session_id: str,
    stage: int,
    db: AsyncSession,
) -> Optional[Note]:
    """Retrieve the latest note version for a specific stage."""
    result = await db.execute(
        select(NoteVersionModel)
        .where(
            NoteVersionModel.session_id == uuid.UUID(session_id),
            NoteVersionModel.stage == stage,
        )
        .order_by(NoteVersionModel.version.desc())
        .limit(1)
    )
    version_record = result.scalar_one_or_none()
    if not version_record:
        return None

    return _deserialize_note(version_record)


async def approve_note(
    session_id: str,
    db: AsyncSession,
) -> Note:
    """Approve the latest note version -- marks it as vFinal.

    Creates a new approved version record. Returns the approved Note.
    Raises ValueError if no note exists for the session.
    """
    result = await db.execute(
        select(NoteVersionModel)
        .where(NoteVersionModel.session_id == uuid.UUID(session_id))
        .order_by(NoteVersionModel.version.desc())
        .limit(1)
    )
    version_record = result.scalar_one_or_none()

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
            section.claims[0].text = new_text
        else:
            section.claims.append(
                NoteClaim(
                    id=f"claim_{uuid.uuid4().hex[:8]}",
                    text=new_text,
                    source_type="transcript",
                    source_id="physician_edit",
                    source_quote="",
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
    result = await db.execute(
        select(NoteVersionModel)
        .where(NoteVersionModel.session_id == uuid.UUID(session_id))
        .order_by(NoteVersionModel.version.asc())
    )
    return list(result.scalars().all())


# ── Deserialization ───────────────────────────────────────────────────────

def _deserialize_note(version_record: NoteVersionModel) -> Note:
    """Deserialize a NoteVersionModel's JSON content into a Note."""
    content = json.loads(version_record.content)
    return Note(**content)
