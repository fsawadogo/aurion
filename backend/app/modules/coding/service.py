"""Coding suggestions extraction + lifecycle service (#69).

Walks the LLM extraction prompt over an approved note, parses the
fenced-JSON array of code candidates, validates each shape, persists
the survivors as `suggested` rows. Physician then confirms / rejects
/ edits through the route layer.

Mirrors `modules.orders.service` in structure. The key difference is
this surface is explicitly INFERENTIAL — the LLM maps free-text
findings to discrete codes — and it must NEVER write into the
clinical note. The data flow is one-way: read note, emit suggestions
into a separate table.

Ownership is enforced by the route — this module trusts its inputs.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CodingSuggestionModel
from app.core.types import Note
from app.modules.coding.catalog import get_catalog_version, validate_code
from app.modules.coding.system_prompt import SYSTEM_PROMPT
from app.modules.config.provider_registry import get_registry
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.coding")

_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL | re.IGNORECASE
)

# Cap the rendered note size sent to the LLM. Same rationale as
# orders / patient_summary: predictable token cost, prompt fits.
_NOTE_RENDER_MAX_CHARS = 6000

# Per-entry required keys for cheap shape validation. Misses get
# dropped silently — partial extraction is better than no extraction.
_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"code_system", "code", "description", "justification"}
)

_ALLOWED_SYSTEMS: frozenset[str] = frozenset({"em", "icd10", "cpt"})
_ALLOWED_CONFIDENCE: frozenset[str] = frozenset({"low", "medium", "high"})

# Format guardrails on the code string itself — defensive only; the
# LLM might emit pretty-printed versions. Loosely constrained so we
# don't drop valid weird codes (modifiers, custom CPT, etc.).
_CODE_RE = re.compile(r"^[A-Z0-9.\-]{2,32}$", re.IGNORECASE)

_DESCRIPTION_MAX = 200
_JUSTIFICATION_MAX = 600


def _render_note_for_prompt(note: Note) -> str:
    """Render the note for the LLM.

    Coding extraction needs the WHOLE clinical picture (HPI for E/M,
    Assessment for ICD-10, Physical Exam / Plan for CPT). Unlike
    orders extraction (which biases toward Plan-side sections), this
    one passes the full populated note up to the budget.
    """
    parts: list[str] = []
    used = 0
    for section in note.sections:
        if section.status != "populated":
            continue
        if not section.claims:
            continue
        title = section.title or section.id.replace("_", " ").title()
        claim_lines = "\n".join(
            f"- [{c.id}] {c.text}" for c in section.claims
        )
        block = f"## {title}\n{claim_lines}"
        if used + len(block) > _NOTE_RENDER_MAX_CHARS:
            block = block[: _NOTE_RENDER_MAX_CHARS - used]
            if not block:
                break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def _parse_extraction(assistant_text: str) -> list[dict[str, Any]]:
    """Pull the fenced JSON array out of the assistant reply and validate.

    Returns the list of well-shaped suggestion candidates. Malformed
    entries are dropped with a log; we never raise on extraction-time
    noise — partial extraction is better than no extraction.
    """
    match = _FENCED_JSON_RE.search(assistant_text)
    if not match:
        logger.warning("coding extraction: no fenced JSON in reply")
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("coding extraction: JSON parse failed: %s", exc)
        return []
    if not isinstance(payload, list):
        logger.warning("coding extraction: expected an array")
        return []

    out: list[dict[str, Any]] = []
    seen_codes: set[tuple[str, str]] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        missing = _REQUIRED_KEYS - entry.keys()
        if missing:
            logger.warning(
                "coding extraction: missing required keys=%s — dropping",
                sorted(missing),
            )
            continue

        system = entry.get("code_system")
        code = entry.get("code")
        description = entry.get("description")
        justification = entry.get("justification")

        if system not in _ALLOWED_SYSTEMS:
            logger.warning("coding extraction: unknown system=%s", system)
            continue
        if not isinstance(code, str) or not _CODE_RE.match(code):
            logger.warning("coding extraction: bad code=%r — dropping", code)
            continue
        if not isinstance(description, str) or not description.strip():
            continue
        if not isinstance(justification, str) or not justification.strip():
            continue

        # Dedupe within a single extraction batch (system, code) tuple.
        key = (system, code.upper())
        if key in seen_codes:
            logger.info(
                "coding extraction: dropping duplicate code=%s in batch", code,
            )
            continue
        seen_codes.add(key)

        confidence = entry.get("confidence", "medium")
        if confidence not in _ALLOWED_CONFIDENCE:
            confidence = "medium"

        source_claim_ids = entry.get("source_claim_ids", [])
        if not isinstance(source_claim_ids, list):
            source_claim_ids = []

        out.append(
            {
                "code_system": system,
                "code": code.upper().strip(),
                "description": description.strip()[:_DESCRIPTION_MAX],
                "justification": justification.strip()[:_JUSTIFICATION_MAX],
                "source_claim_ids": [str(x) for x in source_claim_ids],
                "confidence": confidence,
            }
        )
    return out


async def extract_from_note(
    session_id: uuid.UUID,
    note: Note,
    db: AsyncSession,
) -> tuple[list[CodingSuggestionModel], str]:
    """Run the LLM, persist suggested rows, return them + provider label."""
    rendered = _render_note_for_prompt(note)
    if not rendered:
        return [], "skipped"

    user = (
        "Suggest billing codes for the following approved clinical note. "
        "Follow the system prompt's rules exactly — only suggest codes "
        "the note's claims clearly support. If the note is too sparse, "
        "emit `[]`.\n\n--- NOTE ---\n" + rendered
    )

    provider = get_registry().get_note_provider()
    assistant_text = await provider.generate_text(
        SYSTEM_PROMPT,
        [ChatMessage(role="user", content=user)],
    )
    candidates = _parse_extraction(assistant_text)
    provider_label = (
        type(provider).__name__.replace("NoteGenerationProvider", "").lower()
        or "unknown"
    )

    rows: list[CodingSuggestionModel] = []
    validation_misses = 0
    catalog_version = get_catalog_version()
    for cand in candidates:
        # Catalog validation runs at extraction time, never recomputed
        # on read. Result is stored on the row so the audit story
        # reflects the catalog state at extraction time. A False here
        # means the LLM emitted a code that's not in our curated subset
        # — could still be a real billing code, but verify-before-billing
        # caution applies. The UI surfaces this as a non-blocking warning.
        is_validated = validate_code(cand["code_system"], cand["code"])
        if is_validated is False:
            validation_misses += 1
        row = CodingSuggestionModel(
            id=uuid.uuid4(),
            session_id=session_id,
            code_system=cand["code_system"],
            code=cand["code"],
            description=cand["description"],
            justification=cand["justification"],
            source_claim_ids=cand["source_claim_ids"],
            confidence=cand["confidence"],
            status="suggested",
            code_validated=is_validated,
            catalog_version=catalog_version,
        )
        db.add(row)
        rows.append(row)
    if rows:
        await db.flush()
    if validation_misses:
        logger.info(
            "coding extraction: %d/%d codes not in catalog (version=%s)",
            validation_misses, len(rows), get_catalog_version(),
        )
    return rows, provider_label


async def list_for_session(
    session_id: uuid.UUID, db: AsyncSession
) -> list[CodingSuggestionModel]:
    """All suggestions for a session, newest first. Caller owns auth."""
    stmt = (
        select(CodingSuggestionModel)
        .where(CodingSuggestionModel.session_id == session_id)
        .order_by(CodingSuggestionModel.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_for_session(
    suggestion_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[CodingSuggestionModel]:
    """Fetch a suggestion scoped to its session."""
    stmt = select(CodingSuggestionModel).where(
        CodingSuggestionModel.id == suggestion_id,
        CodingSuggestionModel.session_id == session_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def confirm(
    row: CodingSuggestionModel, db: AsyncSession
) -> CodingSuggestionModel:
    """suggested → confirmed. Idempotent on confirmed; refuses other states."""
    if row.status == "confirmed":
        return row
    if row.status not in ("suggested", "edited"):
        raise ValueError(
            f"Cannot confirm a coding suggestion in {row.status} state"
        )
    row.status = "confirmed"
    row.physician_action_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def reject(
    row: CodingSuggestionModel, db: AsyncSession
) -> CodingSuggestionModel:
    """Reject a suggestion. The row stays for audit (we want to track
    what the LLM proposed and the physician declined); it just won't
    be eligible for EMR write-back."""
    if row.status == "rejected":
        return row
    if row.status == "confirmed":
        raise ValueError("Cannot reject an already-confirmed suggestion")
    row.status = "rejected"
    row.physician_action_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def edit(
    row: CodingSuggestionModel,
    code: str,
    description: str,
    db: AsyncSession,
) -> tuple[CodingSuggestionModel, str]:
    """Edit code and/or description. Returns (row, previous_code) so
    the route can audit the override.

    Edits are accepted from suggested / edited / confirmed states (a
    physician may correct after first confirming); refused from
    rejected (re-confirm first).
    """
    if row.status == "rejected":
        raise ValueError(
            "Cannot edit a rejected suggestion — confirm first to revive it"
        )
    if not _CODE_RE.match(code):
        raise ValueError(f"Invalid code format: {code!r}")
    if not description.strip():
        raise ValueError("Description cannot be empty")

    previous_code = row.code
    row.code = code.upper().strip()
    row.description = description.strip()[:_DESCRIPTION_MAX]
    # Re-run catalog validation since the code itself may have changed.
    # The physician override flips this independently of the LLM's
    # original validation result — a physician-typed code still gets
    # the catalog warning if it's not recognized. Re-stamp the
    # catalog_version too: this validation is against the current
    # catalog, not whatever was in effect at original extraction.
    row.code_validated = validate_code(row.code_system, row.code)
    row.catalog_version = get_catalog_version()
    # Editing implies a physician decision — mark as `edited` so the
    # audit trail distinguishes "physician accepted as-is" from
    # "physician overrode the LLM's pick". UI treats both as eligible
    # for EMR write-back.
    row.status = "edited"
    row.physician_action_at = datetime.now(timezone.utc)
    await db.flush()
    return row, previous_code
