"""Conversational note-review editing ("Fix this note").

Pairs the `NoteGenerationProvider.generate_text` chat path with the `Note`
Pydantic schema, mirroring the template-authoring engine: each turn either
answers conversationally or emits a fenced ```json {"action":"edit_note",
"note":{...}} block. An emitted note is schema-validated AND grounded against
the current version before anything persists — the LLM is never trusted with
provenance:

  * A claim whose ``id`` exists in the current note keeps that claim's
    ``source_type`` / ``source_id`` / ``source_quote`` / ``additional_sources``
    verbatim (restored in code, whatever the LLM echoed). Changed text flips
    ``physician_edited=True`` and stashes ``original_text`` on first edit —
    identical to the manual edit_note path.
  * A claim with an unknown ``id`` is a physician-dictated addition: it is
    forcibly re-sourced to ``source_type="physician_edit"`` /
    ``source_id="pedit_{section_id}"``. No LLM-invented source survives.
  * Sections must be a subset of the current note's — invented or renamed
    sections fail validation and trigger a correction re-prompt.
  * Dropped claims are removals (allowed — "delete the second sentence").

The caller (route layer) persists the applied note through
``note_gen.service.create_note_version`` so every applied instruction is an
immutable, audited version — this module never writes note versions itself.

Chat state lives in ``NoteReviewChatModel`` (one row per session). Messages
may reference note content, so rows are PHI-bearing like note versions:
stored in Postgres, never logged.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import NoteReviewChatModel
from app.core.types import Note
from app.modules.config.provider_registry import get_registry
from app.modules.note_review_chat.system_prompt import SYSTEM_PROMPT
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.note_review_chat")

# Same bounds as template authoring: cap persisted history, cap correction
# re-prompts so an off-shape emission never loops unbounded.
_MAX_MESSAGES = 40
_MAX_VALIDATION_RETRIES = 2

_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class ReviewChatReply:
    """One turn's outcome. ``edited_note`` is set only when the assistant
    emitted a valid, grounded edit — the caller versions + audits it."""

    assistant_message: str
    edited_note: Optional[Note] = None
    sections_edited: list[str] = field(default_factory=list)


class GroundingViolation(ValueError):
    """An emitted note broke a structural grounding rule (invented section,
    duplicated claim id, ...). Triggers a correction re-prompt; never 500s."""


async def get_or_create_chat(
    session_id: uuid.UUID, owner_id: uuid.UUID, db: AsyncSession
) -> NoteReviewChatModel:
    """Fetch the session's chat row, creating it on first use.

    Caller must have already enforced session ownership (the route goes
    through get_owned_session_or_404); ``owner_id`` is recorded so audit
    queries can group by clinician without joining sessions.
    """
    result = await db.execute(
        select(NoteReviewChatModel).where(
            NoteReviewChatModel.session_id == session_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = NoteReviewChatModel(
            session_id=session_id,
            owner_id=owner_id,
            messages_json="[]",
        )
        db.add(row)
        await db.flush()
    return row


async def continue_chat(
    row: NoteReviewChatModel,
    current_note: Note,
    user_message: str,
    db: AsyncSession,
) -> ReviewChatReply:
    """Append a user turn, run the LLM, ground-check any emitted edit.

    The current note is injected as an ephemeral context message on every
    call (never persisted into ``messages_json`` — it would bloat the row
    and go stale the moment an edit is applied).
    """
    user_message = user_message.strip()
    if not user_message:
        raise ValueError("user_message must be non-empty")

    history = _decode_messages(row.messages_json)
    history.append(ChatMessage(role="user", content=user_message))
    history = _truncate_history(history)

    note_context = ChatMessage(
        role="user",
        content=(
            f"CURRENT NOTE (version {current_note.version}) — edit this "
            "and nothing else:\n"
            + json.dumps(current_note.model_dump(), default=str)
        ),
    )

    provider = get_registry().get_note_provider()
    assistant_text, edited, sections = await _generate_with_grounding_retry(
        provider, current_note, [note_context] + history
    )

    history.append(ChatMessage(role="assistant", content=assistant_text))
    history = _truncate_history(history)
    row.messages_json = _encode_messages(history)
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return ReviewChatReply(
        assistant_message=assistant_text,
        edited_note=edited,
        sections_edited=sections,
    )


# ── Internals ──────────────────────────────────────────────────────────────


async def _generate_with_grounding_retry(
    provider,
    current_note: Note,
    call_messages: list[ChatMessage],
) -> tuple[str, Optional[Note], list[str]]:
    """Run the LLM turn; re-prompt on schema/grounding failures up to
    _MAX_VALIDATION_RETRIES times, then surface the reply with no edit."""
    working = list(call_messages)
    last_assistant = ""

    for attempt in range(_MAX_VALIDATION_RETRIES + 1):
        last_assistant = await provider.generate_text(SYSTEM_PROMPT, working)
        candidate = _extract_edit(last_assistant)
        if candidate is None:
            return last_assistant, None, []
        try:
            emitted = Note.model_validate(candidate)
            grounded, sections = _ground_edit(current_note, emitted)
            return last_assistant, grounded, sections
        except (ValidationError, GroundingViolation) as exc:
            detail = (
                exc.errors() if isinstance(exc, ValidationError) else str(exc)
            )
            if attempt == _MAX_VALIDATION_RETRIES:
                logger.warning(
                    "note-review chat: gave up after %d invalid edits; "
                    "surfacing reply without applying. last_errors=%s",
                    _MAX_VALIDATION_RETRIES + 1,
                    detail,
                )
                return last_assistant, None, []
            working = working + [
                ChatMessage(role="assistant", content=last_assistant),
                ChatMessage(
                    role="user",
                    content=(
                        "Your last edit_note action was rejected: "
                        f"{detail}. Re-emit a single valid edit_note action "
                        "for the CURRENT NOTE, echoing untouched claims "
                        "verbatim with their original id/source fields, and "
                        "using source_type \"physician_edit\" only for "
                        "content I explicitly asked you to add."
                    ),
                ),
            ]

    return last_assistant, None, []


def _ground_edit(current: Note, emitted: Note) -> tuple[Note, list[str]]:
    """Diff the emitted note against the current version and enforce every
    provenance rule in code. Returns the grounded note + edited section ids.

    The returned note is built FROM the emitted structure but with source
    fields restored from the current note — the LLM controls text, order,
    and presence of claims; it never controls provenance.
    """
    current_sections = {s.id: s for s in current.sections}
    unknown = [s.id for s in emitted.sections if s.id not in current_sections]
    if unknown:
        raise GroundingViolation(
            f"Sections {unknown} do not exist in the current note; the "
            "section structure is fixed."
        )

    current_claims = {
        c.id: c for section in current.sections for c in section.claims
    }
    seen_claim_ids: set[str] = set()
    grounded = current.model_copy(deep=True)
    grounded_by_id = {s.id: s for s in grounded.sections}
    edited_sections: list[str] = []

    for emitted_section in emitted.sections:
        target = grounded_by_id[emitted_section.id]
        original = current_sections[emitted_section.id]
        new_claims = []
        for emitted_claim in emitted_section.claims:
            if emitted_claim.id in seen_claim_ids:
                raise GroundingViolation(
                    f"Claim id {emitted_claim.id!r} appears more than once."
                )
            seen_claim_ids.add(emitted_claim.id)
            source = current_claims.get(emitted_claim.id)
            if source is not None:
                # Surviving claim: text from the LLM, provenance from us.
                claim = source.model_copy(deep=True)
                if emitted_claim.text != source.text:
                    if not claim.physician_edited:
                        claim.original_text = claim.text
                        claim.physician_edited = True
                    claim.text = emitted_claim.text
            else:
                # Physician-dictated addition: forcibly re-sourced. Fresh id
                # so an LLM echo of a stale/foreign id can't collide.
                claim = emitted_claim.model_copy(deep=True)
                claim.id = f"pclaim_{uuid.uuid4().hex[:8]}"
                claim.source_type = "physician_edit"
                claim.source_id = f"pedit_{emitted_section.id}"
                claim.source_quote = ""
                claim.additional_sources = []
                claim.physician_edited = True
                claim.original_text = None
            new_claims.append(claim)

        changed = (
            [(c.id, c.text) for c in new_claims]
            != [(c.id, c.text) for c in original.claims]
        )
        if changed:
            edited_sections.append(emitted_section.id)
        target.claims = new_claims
        if new_claims:
            target.status = "populated"
        elif original.claims:
            # Every claim removed: nothing captured remains to show.
            target.status = "not_captured"

    # A section absent from the emitted note is untouched — grounded started
    # as a deep copy of current, so it simply carries over.

    if not edited_sections:
        raise GroundingViolation(
            "The edit_note action changed nothing. Reply conversationally "
            "instead when there is nothing to change."
        )
    return grounded, edited_sections


def _extract_edit(assistant_text: str) -> Optional[dict]:
    """Pull the inner ``note`` object out of a fenced edit_note block.
    None for normal conversational turns / unparseable JSON — Pydantic
    catches schema-level invalidity afterwards."""
    match = _FENCED_JSON_RE.search(assistant_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("action") != "edit_note":
        return None
    note = payload.get("note")
    return note if isinstance(note, dict) else None


def _decode_messages(messages_json: str) -> list[ChatMessage]:
    raw = json.loads(messages_json) if messages_json else []
    out: list[ChatMessage] = []
    for item in raw:
        role = item.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        out.append(ChatMessage(role=role, content=item.get("content", "")))
    return out


def _encode_messages(messages: list[ChatMessage]) -> str:
    return json.dumps(
        [{"role": m.role, "content": m.content} for m in messages]
    )


def _truncate_history(history: list[ChatMessage]) -> list[ChatMessage]:
    """Bound persisted history at _MAX_MESSAGES, keeping the most recent
    turns. Unlike template authoring there is no sticky bootstrap message —
    the note context is injected fresh on every call."""
    if len(history) <= _MAX_MESSAGES:
        return history
    return history[-_MAX_MESSAGES:]
