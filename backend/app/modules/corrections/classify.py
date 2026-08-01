"""Correction memory — classify each captured correction.

The post-hoc analysis the roadmap calls for: label every correction a physician
made as one of

  typo     — spelling / grammar / punctuation / capitalisation only; clinical
             meaning unchanged.
  semantic — wording, style, phrasing or structure changed; the SAME clinical
             facts, said differently (the physician's voice/preferences).
  medical  — clinical content changed: a finding, measurement, medication,
             laterality, assessment or plan is different.

Why the split matters downstream: typo + semantic corrections are the mineable
"physician preference" signal (the rules layer) — they're safe to learn from.
medical corrections are NOT a style preference (the model got a clinical fact
wrong once) and must never become an auto-applied rule.

This is a STRUCTURAL classification of an edit, not clinical documentation, so
it runs through the note provider's open-ended ``generate_text`` (no
descriptive-mode rules apply — nothing here writes a note).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CorrectionModel
from app.modules.config.provider_registry import get_registry
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.corrections.classify")

Classification = Literal["typo", "semantic", "medical"]
_VALID: frozenset[str] = frozenset({"typo", "semantic", "medical"})

_CLASSIFY_SYSTEM = (
    "You classify a single edit a physician made to one line of a clinical "
    "note. You are given the text BEFORE and AFTER the edit. Respond with "
    "EXACTLY ONE word, no punctuation, no explanation:\n"
    "  typo     — only spelling, grammar, punctuation or capitalisation "
    "changed; the meaning is identical.\n"
    "  semantic — the wording, phrasing, style or structure changed but the "
    "same clinical facts are stated (a preference in how it is written).\n"
    "  medical  — a clinical fact changed: a finding, measurement, laterality, "
    "medication, assessment or plan is different.\n"
    "When unsure between semantic and medical, choose medical (never treat a "
    "possible clinical change as mere style). Answer with one word only."
)


def _normalise(raw: str) -> Optional[Classification]:
    """Coerce the model's reply to a valid label, or None if unrecognisable."""
    word = raw.strip().lower().split()[0].strip(".,:;\"'") if raw.strip() else ""
    return word if word in _VALID else None  # type: ignore[return-value]


async def classify_one(before: str, after: str) -> Optional[Classification]:
    """Classify a single before→after edit. Returns None on an unusable reply.

    Uses the registry note provider's ``generate_text``. Best-effort: any
    provider error propagates to the caller, which decides whether to skip.
    """
    provider = get_registry().get_note_provider_with_fallback()
    messages = [
        ChatMessage(
            role="user",
            content=f"BEFORE:\n{before}\n\nAFTER:\n{after}\n\nClassification:",
        )
    ]
    reply = await provider.generate_text(_CLASSIFY_SYSTEM, messages)
    label = _normalise(reply)
    if label is None:
        logger.warning("Correction classifier returned an unrecognised label")
    return label


async def classify_pending_for_clinician(
    clinician_id, db: AsyncSession, *, limit: int = 100
) -> dict[str, int]:
    """Classify a clinician's still-unclassified corrections (up to ``limit``).

    Fills the ``classification`` column in place. Returns a per-label count of
    what was classified (plus ``skipped`` for rows the model couldn't label).
    A single row's provider error is swallowed so one bad row can't stall the
    batch. Commits once at the end.
    """
    rows = (
        await db.execute(
            select(CorrectionModel)
            .where(CorrectionModel.clinician_id == clinician_id)
            .where(CorrectionModel.classification.is_(None))
            .order_by(CorrectionModel.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    counts: dict[str, int] = {"typo": 0, "semantic": 0, "medical": 0, "skipped": 0}
    for row in rows:
        try:
            label = await classify_one(row.before_text, row.after_text)
        except Exception:  # noqa: BLE001 — one bad row must not stall the batch
            logger.warning("Classify failed for correction=%s", str(row.id)[:8])
            label = None
        if label is None:
            counts["skipped"] += 1
            continue
        row.classification = label
        counts[label] += 1

    if any(counts[k] for k in ("typo", "semantic", "medical")):
        await db.commit()
    logger.info(
        "Corrections classified: clinician=%s %s",
        str(clinician_id)[:8], counts,
    )
    return counts
