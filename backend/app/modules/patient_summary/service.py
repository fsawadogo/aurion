"""Service for generating + persisting patient-facing visit summaries.

Two write paths:

  * `generate_summary` — fresh LLM call from the approved note; bumps
    the version, marks `physician_edited=False`.
  * `save_edit` — physician replaces the body via the portal modal;
    bumps the version, marks `physician_edited=True`. No LLM call.

Read path is the single `get_latest`: highest version for the
session, or None when no summary exists yet.

Ownership is NOT enforced in this module — callers must confirm the
caller owns the session before invoking these functions. The route
layer handles that via `get_owned_session_or_404`; this service stays
focused on persistence + LLM orchestration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PatientSummaryModel
from app.core.types import Note
from app.modules.config.provider_registry import get_registry

# NOTE: ``SYSTEM_PROMPT`` is no longer referenced directly here —
# AI-PROMPTS-B routes through ``assemble_prompt_for_session`` which
# pulls the base from the prompt registry. The constant remains the
# single source of truth for the base prompt; the registry imports
# it, and so does the safety regression test in
# ``backend/tests/integration/test_me_prompts.py``.
from app.modules.prompts import assemble_prompt_for_session
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.patient_summary")

# Cap the rendered note size sent to the LLM. The full note can be
# substantial; the patient summary doesn't benefit from sections like
# "imaging_review" beyond what the assessment/plan capture. Keeps
# token cost bounded.
_NOTE_RENDER_MAX_CHARS = 6000


async def get_latest(
    session_id: uuid.UUID, db: AsyncSession
) -> Optional[PatientSummaryModel]:
    """Return the highest-version summary for this session, or None."""
    stmt = (
        select(PatientSummaryModel)
        .where(PatientSummaryModel.session_id == session_id)
        .order_by(PatientSummaryModel.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _next_version(
    session_id: uuid.UUID, db: AsyncSession
) -> int:
    latest = await get_latest(session_id, db)
    return (latest.version + 1) if latest else 1


def _render_note_for_prompt(note: Note) -> str:
    """Build the LLM input from the structured note.

    Concatenates section titles + claim text into a single document.
    Stops at _NOTE_RENDER_MAX_CHARS so a runaway note doesn't blow
    the LLM context. The order follows the section order in the
    note (which already mirrors the specialty template).
    """
    parts: list[str] = []
    used = 0
    for section in note.sections:
        if section.status != "populated":
            continue
        if not section.claims:
            continue
        title = section.title or section.id.replace("_", " ").title()
        block = (
            f"{title}:\n"
            + " ".join(c.text for c in section.claims)
        )
        if used + len(block) > _NOTE_RENDER_MAX_CHARS:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


async def generate_summary(
    session_id: uuid.UUID,
    note: Note,
    db: AsyncSession,
) -> PatientSummaryModel:
    """Run a fresh LLM generation and persist as the next version.

    The note must already be approved — that's a precondition the
    route enforces. This function trusts its inputs.

    Raises ProviderError if the LLM call fails — caller maps to 502.
    """
    rendered = _render_note_for_prompt(note)
    if not rendered:
        # Defensive: should never hit because route requires an
        # approved note (which has at least one populated section).
        raise ValueError(
            "Cannot generate a patient summary from a note with no "
            "populated sections."
        )

    user_message = (
        "Rewrite the following clinical note as a patient-facing "
        "after-visit summary, following all the rules in the system "
        "prompt:\n\n--- NOTE ---\n" + rendered
    )

    # AI-PROMPTS-B — select the per-physician REPLACEMENT user prompt
    # when this clinician has saved one; otherwise fall back to the
    # registry default. Sessions without a clinician_id always use the
    # default (defensive — should not happen in production but the
    # helper handles it).
    system_prompt = await assemble_prompt_for_session(
        "patient_summary", session_id, db
    )
    provider = get_registry().get_note_provider()
    body = await provider.generate_text(
        system_prompt,
        [ChatMessage(role="user", content=user_message)],
    )
    body = body.strip()
    if not body:
        raise ValueError("Provider returned an empty summary.")

    version = await _next_version(session_id, db)
    # `provider_used` on the saved row comes from the registry, not
    # from a hardcoded constant — keeps it accurate when AppConfig
    # flips providers.
    provider_label = type(provider).__name__.replace("NoteGenerationProvider", "").lower()
    row = PatientSummaryModel(
        id=uuid.uuid4(),
        session_id=session_id,
        version=version,
        body=body,
        generated_by_provider=provider_label or "unknown",
        physician_edited=False,
    )
    db.add(row)
    await db.flush()
    return row


async def save_edit(
    session_id: uuid.UUID,
    body: str,
    db: AsyncSession,
) -> PatientSummaryModel:
    """Persist a physician's hand-edited summary as the next version.

    Versions never overwrite; each edit creates a fresh row, so the
    edit history is preserved for compliance. Routes call this only
    after confirming ownership.
    """
    cleaned = body.strip()
    if not cleaned:
        raise ValueError("Edited summary must be non-empty.")
    if len(cleaned) > 4000:
        raise ValueError("Edited summary exceeds 4000 chars.")

    version = await _next_version(session_id, db)
    row = PatientSummaryModel(
        id=uuid.uuid4(),
        session_id=session_id,
        version=version,
        body=cleaned,
        # Edited rows keep the original provider attribution from the
        # previous version so the audit story stays clean ("v3 edited
        # by physician; v1/v2 generated by anthropic"). If no prior
        # row exists (physician wrote the first one from scratch),
        # mark provider as 'physician'.
        generated_by_provider=await _previous_provider(session_id, db),
        physician_edited=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _previous_provider(
    session_id: uuid.UUID, db: AsyncSession
) -> str:
    latest = await get_latest(session_id, db)
    return latest.generated_by_provider if latest else "physician"
