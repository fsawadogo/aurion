"""Live preview generation + persistence (#64).

Builds a Transcript shape from the caller's partial transcript text,
calls the note provider with stage=0 (the LLM's contract treats
stage=0 as draft → looser citation requirements, populated sections
ok with sparse evidence), persists a row, returns the Note shape +
the persisted version number for the WebSocket / API caller.

Ownership is enforced by the route — this module trusts its inputs.

The preview pipeline is deliberately a separate code path from
generate_stage1_note:
  * Stage 1 has self-critique + retry + telemetry — preview skips
    those (cost + latency); a bad preview is recoverable on the next
    snapshot
  * Stage 1 persists into NoteVersionModel — preview lives in its own
    table so the canonical pipeline doesn't see preview rows
  * Stage 1 emits the canonical FULL_NOTE_DELIVERED + STAGE1_DELIVERED
    audit events — preview emits LIVE_PREVIEW_GENERATED only
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import LiveNotePreviewModel
from app.core.types import Note, Transcript, TranscriptSegment
from app.modules.config.provider_registry import get_registry
from app.modules.note_gen.service import get_template
from app.modules.prompts import assemble_prompt_for_session

logger = logging.getLogger("aurion.live_preview")

# Bound the transcript we ship to the LLM — previews fire repeatedly
# during a recording; predictable token cost matters more than
# completeness here. The full encounter goes to Stage 1 via the
# canonical pipeline at recording-stop.
_TRANSCRIPT_MAX_CHARS = 8000

# Sentinel stage value for previews. Distinguishes preview rows from
# Stage 1 / Stage 2 versions in any consumer that joins across both
# tables. Stage 1 = 1, Stage 2 = 2, draft preview = 0.
PREVIEW_STAGE = 0


def _build_preview_transcript(
    session_id: str, partial_text: str
) -> Transcript:
    """Wrap the caller's partial transcript text in a single synthetic
    TranscriptSegment so the existing provider.generate_note() pathway
    accepts it without route-side adaptation.

    Real transcript segments come from the canonical transcription
    pipeline (timestamped per-utterance). Previews are best-effort and
    don't have per-utterance timing — collapsing to one segment is
    enough for the LLM to draft sections; downstream consumers MUST
    NOT treat preview source_id values as canonical anchors.
    """
    capped = partial_text[-_TRANSCRIPT_MAX_CHARS:]
    return Transcript(
        session_id=session_id,
        provider_used="live_preview_synthetic",
        segments=[
            TranscriptSegment(
                id="preview_seg_0",
                start_ms=0,
                end_ms=0,
                text=capped,
            )
        ],
    )


async def _next_version(
    session_id: uuid.UUID, db: AsyncSession
) -> int:
    """Next sequential preview version number for the session.

    1-indexed; uses a SELECT MAX so concurrent writes don't share a
    version (the table's UNIQUE constraint catches collisions; a
    second SELECT-then-INSERT loop would be overkill for a pilot at
    sub-second cadence)."""
    stmt = (
        select(LiveNotePreviewModel.version)
        .where(LiveNotePreviewModel.session_id == session_id)
        .order_by(LiveNotePreviewModel.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    latest = result.scalar_one_or_none()
    return (latest or 0) + 1


async def generate_preview(
    session_id: uuid.UUID,
    specialty: str,
    partial_transcript: str,
    db: AsyncSession,
    output_language: str = "en",
) -> tuple[LiveNotePreviewModel, int]:
    """Run a preview-stage LLM call, persist the row, return it +
    elapsed-ms.

    Returns (row, latency_ms). Latency is what the route emits in the
    audit event so the pilot can chart preview latency over the
    encounter without joining audit rows back to created_at.
    """
    template = get_template(specialty)
    transcript = _build_preview_transcript(str(session_id), partial_transcript)
    registry = get_registry()
    provider = registry.get_note_provider()

    # AI-PROMPTS-B — assemble the ``live_preview`` overlay for the
    # session's clinician. Same registry entry the Transparency page
    # surfaces; same per-physician scope.
    system_prompt = await assemble_prompt_for_session(
        "live_preview", session_id, db
    )

    started = time.monotonic()
    note: Note = await provider.generate_note(
        transcript,
        template,
        stage=PREVIEW_STAGE,
        output_language=output_language,
        system_prompt=system_prompt,
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    version = await _next_version(session_id, db)
    provider_label = (
        type(provider).__name__.replace("NoteGenerationProvider", "").lower()
        or "unknown"
    )

    # Sections come back as Pydantic models — dump to plain JSON for
    # storage. JSONB column accepts list[dict] cleanly.
    sections_json = [s.model_dump(mode="json") for s in note.sections]

    row = LiveNotePreviewModel(
        id=uuid.uuid4(),
        session_id=session_id,
        version=version,
        sections=sections_json,
        transcript_chars=len(partial_transcript),
        completeness_score=note.completeness_score,
        provider_used=provider_label,
    )
    db.add(row)
    await db.flush()
    return row, latency_ms


async def list_for_session(
    session_id: uuid.UUID, db: AsyncSession
) -> list[LiveNotePreviewModel]:
    """All previews for a session, newest first."""
    stmt = (
        select(LiveNotePreviewModel)
        .where(LiveNotePreviewModel.session_id == session_id)
        .order_by(LiveNotePreviewModel.version.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_latest_for_session(
    session_id: uuid.UUID, db: AsyncSession
) -> Optional[LiveNotePreviewModel]:
    """The most recent preview row, or None when no previews exist
    for this session yet."""
    stmt = (
        select(LiveNotePreviewModel)
        .where(LiveNotePreviewModel.session_id == session_id)
        .order_by(LiveNotePreviewModel.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
