"""Correction memory — capture in-app physician note edits.

The moat: every time a clinician corrects the generated note in-app, we log the
before/after text so the system can later classify the correction (typo /
semantic / medical) and distil the patterns into per-physician rules. This
module is the CAPTURE layer — the roadmap's "ship logging first, mine later".

Capture is a pure function over the edited note: an edit sets
``NoteClaim.original_text`` (the pre-edit text) and ``physician_edited=True`` on
the changed claim, so a correction is any physician-edited claim in an edited
section whose text actually changed. No PHI leaves the note-content boundary —
the rows live owner-scoped alongside the note versions they came from.

Gated by ``feature_flags.correction_memory_enabled`` at the call site; this
module records unconditionally when called, so it stays trivially testable.
"""

from __future__ import annotations

import logging
import uuid
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CorrectionModel
from app.core.types import Note

logger = logging.getLogger("aurion.corrections")


def _corrections_from_note(
    note: Note, edited_section_ids: Iterable[str]
) -> list[tuple[str, str, str, str]]:
    """Pure diff: the (section_id, claim_id, before, after) tuples an edit made.

    A correction is a physician-edited claim, in one of the edited sections,
    whose ``original_text`` differs from its current ``text``. Ordered by
    section then claim for determinism.
    """
    wanted = set(edited_section_ids)
    out: list[tuple[str, str, str, str]] = []
    for section in note.sections:
        if section.id not in wanted:
            continue
        for claim in section.claims:
            if not claim.physician_edited:
                continue
            before = claim.original_text
            if before is None or before == claim.text:
                continue
            out.append((section.id, claim.id, before, claim.text))
    return out


async def record_corrections(
    clinician_id: uuid.UUID,
    session_id: uuid.UUID,
    note: Note,
    edited_section_ids: Iterable[str],
    db: AsyncSession,
) -> int:
    """Persist one CorrectionModel row per real edit in the edited sections.

    Returns the number of corrections recorded. Best-effort: it flushes the
    rows on the caller's session but does not commit (the caller's transaction
    owns the commit, alongside the note version). ``classification`` is left
    NULL for the later analysis pass. Never raises on an empty diff.
    """
    diffs = _corrections_from_note(note, edited_section_ids)
    for section_id, claim_id, before, after in diffs:
        db.add(
            CorrectionModel(
                clinician_id=clinician_id,
                session_id=session_id,
                section_id=section_id,
                claim_id=claim_id,
                before_text=before,
                after_text=after,
                classification=None,
                note_version=note.version,
            )
        )
    if diffs:
        await db.flush()
        logger.info(
            "Corrections captured: clinician=%s session=%s count=%d",
            str(clinician_id)[:8], str(session_id)[:8], len(diffs),
        )
    return len(diffs)
