"""Orders extraction + lifecycle service.

Walks the LLM extraction prompt over an approved note, parses the
fenced-JSON array of order candidates, validates each shape, persists
the survivors as `draft` rows. Physician then confirms / edits /
cancels through the route layer.

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

from app.core.models import NoteOrderModel
from app.core.types import Note
from app.modules.config.provider_registry import get_registry
from app.modules.orders.drug_catalog import get_catalog_version, validate_drug
from app.modules.orders.system_prompt import SYSTEM_PROMPT
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.orders")

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL | re.IGNORECASE)

# Cap the rendered note size sent to the LLM (same rationale as
# patient_summary: predictable token cost, prompt fits in context).
_NOTE_RENDER_MAX_CHARS = 6000

# Per-kind required `details` keys for cheap shape validation. Empty
# string values are allowed (frequency might be PRN, laterality might
# be null); missing keys are not. Misses get dropped silently so a
# malformed LLM emission doesn't crash the whole extraction.
_REQUIRED_DETAILS_KEYS: dict[str, set[str]] = {
    "imaging": {"modality", "body_part", "indication"},
    "lab": {"panel", "indication"},
    "referral": {"specialty", "reason"},
    "prescription": {"drug", "dose", "frequency", "indication"},
}

_ALLOWED_KINDS = frozenset(_REQUIRED_DETAILS_KEYS.keys())


def _render_note_for_prompt(note: Note) -> str:
    """Build the LLM input — focus on the Plan-side sections.

    Imaging Review / Plan / Investigations are where orderable
    actions live in every specialty template; other sections rarely
    contain dictated orders. Mirrors patient_summary's renderer but
    biases section selection toward action-oriented content.
    """
    relevant_ids = {
        "plan", "imaging_review", "investigations", "disposition", "assessment",
    }
    parts: list[str] = []
    used = 0
    for section in note.sections:
        if section.status != "populated":
            continue
        if not section.claims:
            continue
        # Bias inclusion: action-sections always pass; everything else
        # gets added only if the budget permits, in case the physician
        # buried the order in a non-canonical section.
        is_relevant = (section.id in relevant_ids)
        title = section.title or section.id.replace("_", " ").title()
        claim_lines = "\n".join(
            f"- [{c.id}] {c.text}" for c in section.claims
        )
        block = f"## {title}\n{claim_lines}"
        if used + len(block) > _NOTE_RENDER_MAX_CHARS:
            if not is_relevant:
                continue
            # Truncate the block rather than skip the relevant section.
            block = block[: _NOTE_RENDER_MAX_CHARS - used]
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def _parse_extraction(assistant_text: str) -> list[dict[str, Any]]:
    """Pull the fenced JSON array out of the assistant reply and validate.

    Returns the list of well-shaped order candidates. Malformed entries
    are dropped with a log; we never raise on extraction-time noise,
    because partial extraction is better than no extraction.
    """
    match = _FENCED_JSON_RE.search(assistant_text)
    if not match:
        logger.warning("orders extraction: no fenced JSON in reply")
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("orders extraction: JSON parse failed: %s", exc)
        return []
    if not isinstance(payload, list):
        logger.warning("orders extraction: expected an array")
        return []

    out: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        details = entry.get("details")
        if kind not in _ALLOWED_KINDS:
            logger.warning("orders extraction: unknown kind=%s — dropping", kind)
            continue
        if not isinstance(details, dict):
            continue
        required = _REQUIRED_DETAILS_KEYS[kind]
        missing = required - details.keys()
        if missing:
            logger.warning(
                "orders extraction: kind=%s missing required keys=%s — dropping",
                kind, missing,
            )
            continue
        source_claim_ids = entry.get("source_claim_ids", [])
        if not isinstance(source_claim_ids, list):
            source_claim_ids = []
        out.append(
            {
                "kind": kind,
                "details": details,
                "source_claim_ids": [str(x) for x in source_claim_ids],
            }
        )
    return out


async def extract_from_note(
    session_id: uuid.UUID,
    note: Note,
    db: AsyncSession,
) -> tuple[list[NoteOrderModel], str]:
    """Run the LLM, persist draft rows, return them + the provider label.

    Returns (rows, provider_label) so the caller can build an audit
    event without re-discovering which provider fired.
    """
    rendered = _render_note_for_prompt(note)
    if not rendered:
        return [], "skipped"

    user = (
        "Extract orderable actions from the following approved clinical "
        "note. Follow the system prompt's rules exactly — only extract "
        "what the note already records.\n\n--- NOTE ---\n" + rendered
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

    rows: list[NoteOrderModel] = []
    drug_misses = 0
    catalog_version = get_catalog_version()
    for cand in candidates:
        # Drug catalog validation runs at extraction time for
        # prescription rows only. Other kinds (imaging / lab /
        # referral) don't have a drug field; their drug_validated
        # column stays NULL. The False / None distinction matters in
        # the audit story and in the UI badge.
        drug_validated: bool | None = None
        row_catalog_version: str | None = None
        if cand["kind"] == "prescription":
            raw_drug = cand["details"].get("drug", "")
            drug_validated = validate_drug(raw_drug)
            row_catalog_version = catalog_version
            if drug_validated is False:
                drug_misses += 1
        row = NoteOrderModel(
            id=uuid.uuid4(),
            session_id=session_id,
            kind=cand["kind"],
            details=cand["details"],
            source_claim_ids=cand["source_claim_ids"],
            status="draft",
            drug_validated=drug_validated,
            catalog_version=row_catalog_version,
        )
        db.add(row)
        rows.append(row)
    if rows:
        await db.flush()
    if drug_misses:
        logger.info(
            "orders extraction: %d prescription drugs not in catalog (version=%s)",
            drug_misses, get_catalog_version(),
        )
    return rows, provider_label


async def list_for_session(
    session_id: uuid.UUID, db: AsyncSession
) -> list[NoteOrderModel]:
    """All orders for a session, newest first. Caller owns auth."""
    stmt = (
        select(NoteOrderModel)
        .where(NoteOrderModel.session_id == session_id)
        .order_by(NoteOrderModel.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_for_session(
    order_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[NoteOrderModel]:
    """Fetch an order, scoped to its session. None when it doesn't
    exist OR belongs to a different session (caller maps to 404)."""
    stmt = select(NoteOrderModel).where(
        NoteOrderModel.id == order_id,
        NoteOrderModel.session_id == session_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def confirm(
    row: NoteOrderModel, db: AsyncSession
) -> NoteOrderModel:
    """Draft → confirmed. No-op if already confirmed (returns the row
    unchanged so the route can be idempotent). Other transitions raise."""
    if row.status == "confirmed":
        return row
    if row.status != "draft":
        raise ValueError(
            f"Cannot confirm an order in {row.status} state; expected draft"
        )
    row.status = "confirmed"
    row.physician_confirmed_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def edit_details(
    row: NoteOrderModel,
    details: dict[str, Any],
    db: AsyncSession,
) -> NoteOrderModel:
    """Edit the order's details. Allowed in draft + confirmed (the
    physician may tweak even after confirming); refused in sent (the
    EMR has it) or cancelled. Re-validates shape against the kind."""
    if row.status in ("sent", "cancelled"):
        raise ValueError(
            f"Cannot edit an order in {row.status} state"
        )
    required = _REQUIRED_DETAILS_KEYS[row.kind]
    missing = required - details.keys()
    if missing:
        raise ValueError(
            f"Missing required {row.kind} keys: {sorted(missing)}"
        )
    row.details = details
    # Re-run drug validation when the drug field may have changed
    # (only meaningful for prescription rows). A physician-typed
    # bogus drug name still gets the warning — same safety contract
    # as the extraction path. Re-stamp the catalog version too:
    # this validation result is against the CURRENT catalog, not
    # whatever was in effect at the original extraction.
    if row.kind == "prescription":
        row.drug_validated = validate_drug(details.get("drug", ""))
        row.catalog_version = get_catalog_version()
    await db.flush()
    return row


async def cancel(row: NoteOrderModel, db: AsyncSession) -> NoteOrderModel:
    """Draft / confirmed → cancelled. Sent orders can't be cancelled
    in-system (the EMR is the source of truth for those)."""
    if row.status == "sent":
        raise ValueError("Cannot cancel a sent order in-system")
    row.status = "cancelled"
    await db.flush()
    return row
