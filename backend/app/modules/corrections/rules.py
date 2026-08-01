"""Correction memory — per-physician rules distilled from corrections.

The payoff of the correction-memory chain: the physician's accepted corrections
become reusable RULES that shape future notes, so the system learns their voice
("that is how you fall in love with the product"). This module is the rules
layer:

  * store   — a physician's accepted rules block (reuses PromptOverrideModel
              under a single ``correction_rules`` namespace, no new table).
  * suggest — distil the physician's typo + semantic corrections into candidate
              rule lines the UI offers with "would you like this to be the rule
              from now on?". MEDICAL corrections are excluded — a one-off
              clinical fix is never a style preference.
  * render  — the rules block, fenced BELOW the descriptive boundary, for
              injection into note generation (gated by
              ``correction_rules_in_prompt_enabled``).

The rules are PHI-free physician preferences ("use 'the patient' not 'the
client'", "spell out ROM as range of motion"), NOT patient data and NOT model
training — the roadmap's data-governance line.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CorrectionModel, PromptOverrideModel
from app.modules.config.provider_registry import get_registry
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.corrections.rules")

# Single per-physician namespace in prompt_overrides (rules are global to the
# physician, not per-specialty — contrast specialty_style:<key>).
CORRECTION_RULES_PROMPT_ID = "correction_rules"

# How many candidate rules the suggester may return, and how many corrections
# it reads — bounded so the distillation call stays cheap.
_MAX_SUGGESTIONS = 8
_MAX_CORRECTIONS_READ = 60

_SUGGEST_SYSTEM = (
    "You are given a list of edits a physician repeatedly made to their "
    "clinical notes — the BEFORE text and the AFTER text of each. Infer the "
    "GENERAL WRITING PREFERENCES behind them and state each as one short "
    "imperative rule the note writer could follow next time (e.g. \"Refer to "
    "the person as 'the patient', not 'the client'\", \"Spell out abbreviations "
    "on first use\"). Rules must be about STYLE and WORDING only — never a "
    "clinical instruction, a diagnosis, or anything that changes clinical "
    "meaning. Only propose a rule when the SAME preference appears more than "
    "once. Return one rule per line, no numbering, no preamble. If no clear "
    "repeated preference exists, return nothing."
)


async def get_correction_rules(clinician_id: uuid.UUID, db: AsyncSession) -> str:
    """The physician's saved correction-rules block, or "" when none."""
    text = (
        await db.execute(
            select(PromptOverrideModel.user_prompt_text).where(
                PromptOverrideModel.owner_id == clinician_id,
                PromptOverrideModel.prompt_id == CORRECTION_RULES_PROMPT_ID,
            )
        )
    ).scalar_one_or_none()
    return (text or "").strip()


async def set_correction_rules(
    clinician_id: uuid.UUID, text: str, db: AsyncSession
) -> None:
    """Upsert the physician's correction-rules block (their accepted rules)."""
    row = (
        await db.execute(
            select(PromptOverrideModel).where(
                PromptOverrideModel.owner_id == clinician_id,
                PromptOverrideModel.prompt_id == CORRECTION_RULES_PROMPT_ID,
            )
        )
    ).scalar_one_or_none()
    clean = text.strip()
    if row is None:
        db.add(
            PromptOverrideModel(
                id=uuid.uuid4(),
                owner_id=clinician_id,
                prompt_id=CORRECTION_RULES_PROMPT_ID,
                user_prompt_text=clean,
            )
        )
    else:
        row.user_prompt_text = clean
    await db.flush()


async def suggest_rules(clinician_id: uuid.UUID, db: AsyncSession) -> list[str]:
    """Distil the physician's typo + semantic corrections into candidate rules.

    MEDICAL corrections are excluded (a clinical fix is not a style preference).
    Returns up to ``_MAX_SUGGESTIONS`` rule lines; [] when there is nothing
    clear to learn or too few corrections to generalise.
    """
    rows = (
        await db.execute(
            select(CorrectionModel)
            .where(CorrectionModel.clinician_id == clinician_id)
            .where(CorrectionModel.classification.in_(("typo", "semantic")))
            .order_by(CorrectionModel.created_at.desc())
            .limit(_MAX_CORRECTIONS_READ)
        )
    ).scalars().all()
    if len(rows) < 2:
        return []

    examples = "\n".join(
        f"- BEFORE: {r.before_text}\n  AFTER: {r.after_text}" for r in rows
    )
    provider = get_registry().get_note_provider_with_fallback()
    try:
        reply = await provider.generate_text(
            _SUGGEST_SYSTEM,
            [ChatMessage(role="user", content=f"Edits:\n{examples}\n\nRules:")],
        )
    except Exception:  # noqa: BLE001 — suggestion is best-effort
        logger.warning("Rule suggestion failed for clinician=%s", str(clinician_id)[:8])
        return []

    lines = [
        line.strip().lstrip("-•*0123456789. ").strip()
        for line in reply.splitlines()
        if line.strip()
    ]
    # De-dup while preserving order; bound the count.
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower()
        if line and key not in seen:
            seen.add(key)
            out.append(line)
        if len(out) >= _MAX_SUGGESTIONS:
            break
    return out


async def render_correction_rules_prefix(
    clinician_id: Optional[uuid.UUID], db: AsyncSession
) -> Optional[str]:
    """The rules block fenced for note-gen system-prompt injection, or None.

    Fenced BELOW the descriptive boundary and framed strictly as style
    preferences, so a rule can shape WORDING but never loosen grounding or
    inject a clinical instruction (the same discipline as the specialty-style
    layer). None when the physician has no rules.
    """
    if clinician_id is None:
        return None
    rules = await get_correction_rules(clinician_id, db)
    if not rules:
        return None
    return (
        "\n\nPHYSICIAN WRITING PREFERENCES (style only — apply when phrasing the "
        "note; these NEVER change clinical content, add findings, or relax the "
        "rule that every statement stays grounded in the captured source):\n"
        f"{rules}"
    )
