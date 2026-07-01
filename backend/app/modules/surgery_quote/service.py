"""Service for generating + persisting patient-facing surgery quotes.

Two write paths (mirrors patient_summary):

  * ``generate_quote`` — fresh LLM call from the approved note. The model
    extracts the procedures the note records as discussed; each becomes a
    line item with an EMPTY fee (the physician prices it). Bumps the
    version, ``physician_edited=False``.
  * ``save_edit`` — physician replaces the line items / fees / notes; bumps
    the version, ``physician_edited=True``. No LLM call.

Read path is the single ``get_latest``. Ownership is enforced by the route
layer (``get_owned_session_or_404``); this service stays focused on
persistence + LLM orchestration.

Money is stored as integer cents (``fee_cents``) to avoid float drift; a
``None`` fee means "not yet priced". No price is ever produced by the LLM.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import SurgeryQuoteModel
from app.core.types import Note
from app.modules.config.provider_registry import get_registry

# The base prompt is registered in prompts/registry.py under "surgery_quote";
# assemble_prompt_for_session pulls it (+ any per-physician override). The
# constant remains the single source of truth (registry + safety test import
# it).
from app.modules.prompts import assemble_prompt_for_session
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.surgery_quote")

_NOTE_RENDER_MAX_CHARS = 6000
_MAX_LINE_ITEMS = 30
_MAX_PROCEDURE_LEN = 200
_MAX_DESCRIPTION_LEN = 600
_MAX_NOTES_LEN = 2000
_DEFAULT_CURRENCY = "CAD"  # Quebec pilot (CREOQ/CLLC)


async def get_latest(
    session_id: uuid.UUID, db: AsyncSession
) -> Optional[SurgeryQuoteModel]:
    """Return the highest-version quote for this session, or None."""
    stmt = (
        select(SurgeryQuoteModel)
        .where(SurgeryQuoteModel.session_id == session_id)
        .order_by(SurgeryQuoteModel.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _next_version(session_id: uuid.UUID, db: AsyncSession) -> int:
    latest = await get_latest(session_id, db)
    return (latest.version + 1) if latest else 1


def _render_note_for_prompt(note: Note) -> str:
    """Concatenate populated section titles + claim text (capped)."""
    parts: list[str] = []
    used = 0
    for section in note.sections:
        if section.status != "populated" or not section.claims:
            continue
        title = section.title or section.id.replace("_", " ").title()
        block = f"{title}:\n" + " ".join(c.text for c in section.claims)
        if used + len(block) > _NOTE_RENDER_MAX_CHARS:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def _parse_line_items(raw: str) -> list[dict[str, Any]]:
    """Parse the LLM's JSON array of {procedure, description} into stored
    line items with a generated id + an empty (physician-filled) fee.

    Defensive: strips markdown fences, tolerates a wrapping object, drops
    malformed entries, caps the count. NEVER reads a fee from the model
    (fees are physician-entered) — any ``fee``-ish key is ignored.
    """
    text = raw.strip()
    # Strip ```json ... ``` fences some models add despite instructions.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("surgery_quote: could not parse LLM output as JSON")
        return []
    # Tolerate {"items": [...]} / {"procedures": [...]} wrappers.
    if isinstance(data, dict):
        for key in ("items", "procedures", "line_items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []

    items: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        procedure = str(entry.get("procedure", "")).strip()[:_MAX_PROCEDURE_LEN]
        if not procedure:
            continue
        description = str(entry.get("description", "")).strip()[
            :_MAX_DESCRIPTION_LEN
        ]
        items.append(
            {
                "id": "li_" + uuid.uuid4().hex[:8],
                "procedure": procedure,
                "description": description,
                # Always empty on generation — the physician prices it. The
                # model is forbidden from producing a fee.
                "fee_cents": None,
            }
        )
        if len(items) >= _MAX_LINE_ITEMS:
            break
    return items


async def generate_quote(
    session_id: uuid.UUID,
    note: Note,
    db: AsyncSession,
) -> SurgeryQuoteModel:
    """Run a fresh LLM extraction and persist as the next version.

    The note must already be approved — the route enforces that. Raises
    ``ProviderError`` if the LLM call fails (caller maps to 502).
    """
    rendered = _render_note_for_prompt(note)
    if not rendered:
        raise ValueError(
            "Cannot generate a surgery quote from a note with no "
            "populated sections."
        )

    user_message = (
        "Extract the surgical/procedural line items discussed in the "
        "following clinical note, following all the rules in the system "
        "prompt. Return the JSON array only:\n\n--- NOTE ---\n" + rendered
    )
    system_prompt = await assemble_prompt_for_session(
        "surgery_quote", session_id, db
    )
    provider = get_registry().get_note_provider()
    raw = await provider.generate_text(
        system_prompt,
        [ChatMessage(role="user", content=user_message)],
    )
    line_items = _parse_line_items(raw)

    version = await _next_version(session_id, db)
    provider_label = (
        type(provider).__name__.replace("NoteGenerationProvider", "").lower()
    )
    row = SurgeryQuoteModel(
        id=uuid.uuid4(),
        session_id=session_id,
        version=version,
        line_items=line_items,
        currency=_DEFAULT_CURRENCY,
        notes=None,
        generated_by_provider=provider_label or "unknown",
        physician_edited=False,
    )
    db.add(row)
    await db.flush()
    return row


def _validate_edit_line_items(
    raw_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate + normalize physician-supplied line items.

    Each item: ``procedure`` (required, non-empty), ``description``
    (optional), ``fee_cents`` (optional int >= 0, or None = unpriced). Ids
    are preserved when well-formed, minted otherwise.
    """
    if len(raw_items) > _MAX_LINE_ITEMS:
        raise ValueError(f"A quote may have at most {_MAX_LINE_ITEMS} items.")
    cleaned: list[dict[str, Any]] = []
    for entry in raw_items:
        procedure = str(entry.get("procedure", "")).strip()
        if not procedure:
            raise ValueError("Each line item needs a procedure name.")
        if len(procedure) > _MAX_PROCEDURE_LEN:
            raise ValueError("Procedure name is too long.")
        description = str(entry.get("description", "") or "").strip()
        if len(description) > _MAX_DESCRIPTION_LEN:
            raise ValueError("Description is too long.")
        fee = entry.get("fee_cents", None)
        if fee is not None:
            if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
                raise ValueError("fee_cents must be a non-negative integer.")
        item_id = str(entry.get("id", "")).strip()
        if not re.fullmatch(r"li_[0-9a-f]{8}", item_id):
            item_id = "li_" + uuid.uuid4().hex[:8]
        cleaned.append(
            {
                "id": item_id,
                "procedure": procedure[:_MAX_PROCEDURE_LEN],
                "description": description[:_MAX_DESCRIPTION_LEN],
                "fee_cents": fee,
            }
        )
    return cleaned


async def save_edit(
    session_id: uuid.UUID,
    line_items: list[dict[str, Any]],
    db: AsyncSession,
    currency: Optional[str] = None,
    notes: Optional[str] = None,
) -> SurgeryQuoteModel:
    """Persist a physician-edited quote as the next version (no LLM call)."""
    cleaned_items = _validate_edit_line_items(line_items)
    cur = (currency or _DEFAULT_CURRENCY).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise ValueError("currency must be a 3-letter ISO code.")
    cleaned_notes: Optional[str] = None
    if notes is not None:
        stripped = notes.strip()
        if len(stripped) > _MAX_NOTES_LEN:
            raise ValueError("Notes exceed the length limit.")
        cleaned_notes = stripped or None

    version = await _next_version(session_id, db)
    row = SurgeryQuoteModel(
        id=uuid.uuid4(),
        session_id=session_id,
        version=version,
        line_items=cleaned_items,
        currency=cur,
        notes=cleaned_notes,
        generated_by_provider=await _previous_provider(session_id, db),
        physician_edited=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _previous_provider(session_id: uuid.UUID, db: AsyncSession) -> str:
    latest = await get_latest(session_id, db)
    return latest.generated_by_provider if latest else "physician"
