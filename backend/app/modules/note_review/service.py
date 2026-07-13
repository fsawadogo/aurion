"""Note-review assistant engine — request → validated edit ops → new version.

Stateless per turn: the current note IS the conversation state, so each request
carries only the physician's message (no server-side chat history → no PHI
message store). The LLM output path mirrors the established `generate_text` +
fenced-JSON + validate-and-retry pattern (template authoring / orders / coding);
the apply path mirrors `resolve_conflict`'s deep-copy + original_text /
physician_edited invariants and funnels through `create_note_version`.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import TranscriptModel
from app.core.types import Note, NoteClaim, Transcript
from app.core.uuids import to_uuid
from app.modules.config.provider_registry import get_registry
from app.modules.note_gen.service import create_note_version, get_latest_note
from app.modules.prompts import assemble_prompt_for_session
from app.modules.providers.base import ChatMessage

logger = logging.getLogger("aurion.note_review")

_MAX_VALIDATION_RETRIES = 2
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_MAX_SOURCE_QUOTE = 500


class NoteEditOp(BaseModel):
    """One edit operation the physician's request maps to.

    ``op`` is the discriminator; the other fields are per-op (validated in
    ``_apply_ops``). ``source_id`` on an ``add_claim`` is a transcript seg id
    that grounds the addition — omitted or unknown means the claim is recorded
    as a physician edit, never a fabricated citation.
    """

    op: Literal["reword_claim", "remove_claim", "add_claim"]
    claim_id: Optional[str] = None
    section_id: Optional[str] = None
    text: Optional[str] = None
    source_id: Optional[str] = None


@dataclass(frozen=True)
class AssistResult:
    assistant_message: str
    applied: bool
    note: Note


async def assist_note(session_id: str, message: str, db: AsyncSession) -> AssistResult:
    """Apply the physician's plain-language request to the latest note.

    When the model emits edit ops they are validated + applied onto a deep copy
    and saved as a new version. When it replies conversationally (a clarifying
    question), the note is returned unchanged (``applied=False``) and no version
    is written. Does NOT commit — the route owns the commit.
    """
    message = message.strip()
    if not message:
        raise ValueError("message must be non-empty")

    note = await get_latest_note(session_id, db)
    if note is None:
        raise ValueError(f"No note found for session {session_id}")

    transcript = await _load_transcript(session_id, db)
    segment_text = (
        {seg.id: seg.text for seg in transcript.segments} if transcript else {}
    )

    provider = get_registry().get_note_provider()
    system_prompt = await assemble_prompt_for_session("note_review", session_id, db)
    user_prompt = _build_user_prompt(note, transcript, message)

    assistant_message, ops = await _generate_edits_with_retry(
        provider, system_prompt, user_prompt
    )
    if not ops:
        return AssistResult(assistant_message=assistant_message, applied=False, note=note)

    updated, applied = _apply_ops(note, ops, segment_text)
    if applied == 0:
        return AssistResult(assistant_message=assistant_message, applied=False, note=note)

    await create_note_version(
        session_id, updated, db, stats_trigger="note_review_assist"
    )
    logger.info(
        "note-review assist: session=%s applied=%d new_version=%d",
        session_id,
        applied,
        updated.version,
    )
    return AssistResult(assistant_message=assistant_message, applied=True, note=updated)


# ── Internals ──────────────────────────────────────────────────────────────


async def _load_transcript(session_id: str, db: AsyncSession) -> Optional[Transcript]:
    """Best-effort transcript fetch — segment ids ground added claims."""
    row = (
        await db.execute(
            select(TranscriptModel).where(
                TranscriptModel.session_id == to_uuid(session_id)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return Transcript.model_validate(json.loads(row.transcript_json))
    except (json.JSONDecodeError, ValueError):
        return None


def _build_user_prompt(
    note: Note, transcript: Optional[Transcript], message: str
) -> str:
    note_repr = json.dumps(
        [
            {
                "section_id": s.id,
                "title": s.title,
                "claims": [{"claim_id": c.id, "text": c.text} for c in s.claims],
            }
            for s in note.sections
        ],
        indent=2,
    )
    segs = transcript.segments if transcript else []
    transcript_repr = json.dumps(
        [{"seg_id": seg.id, "text": seg.text} for seg in segs], indent=2
    )
    return (
        f"CURRENT NOTE:\n{note_repr}\n\n"
        "TRANSCRIPT SEGMENTS (cite a seg_id only to ground an addition; never "
        f"invent one):\n{transcript_repr}\n\n"
        f"PHYSICIAN REQUEST:\n{message}"
    )


async def _generate_edits_with_retry(
    provider, system_prompt: str, user_prompt: str
) -> tuple[str, list[NoteEditOp]]:
    """Run the LLM turn; return ``(assistant_message, ops)``.

    ``ops`` is ``[]`` for a conversational reply (no edit_note block) or after
    exhausting retries on malformed ops — surfacing the reply without editing
    rather than raising.
    """
    working: list[ChatMessage] = [ChatMessage(role="user", content=user_prompt)]
    last_text = ""
    for attempt in range(_MAX_VALIDATION_RETRIES + 1):
        last_text = await provider.generate_text(system_prompt, working)
        payload = _extract_edit_payload(last_text)
        if payload is None:
            # Conversational turn (e.g. a clarifying question) — no edits.
            return last_text, []
        message = payload.get("message") or "Updated the note."
        raw_ops = payload.get("ops") or []
        try:
            ops = [NoteEditOp.model_validate(o) for o in raw_ops]
            return message, ops
        except ValidationError as exc:
            if attempt == _MAX_VALIDATION_RETRIES:
                logger.warning(
                    "note-review: gave up after %d invalid op sets; no edits applied.",
                    _MAX_VALIDATION_RETRIES + 1,
                )
                return message, []
            # Summarize to loc+msg only (Pydantic's `input` can carry note text).
            safe = "; ".join(
                f"{'.'.join(str(p) for p in e.get('loc', ())) or 'ops'}: "
                f"{e.get('msg', 'invalid')}"
                for e in exc.errors()
            )
            working = working + [
                ChatMessage(role="assistant", content=last_text),
                ChatMessage(
                    role="user",
                    content=(
                        f"Your ops failed validation: {safe}. Re-emit a single valid "
                        "edit_note block; each op needs its required fields "
                        "(reword_claim: claim_id+text; remove_claim: claim_id; "
                        "add_claim: section_id+text)."
                    ),
                ),
            ]
    return last_text, []


def _extract_edit_payload(assistant_text: str) -> Optional[dict]:
    """Pull the ``{"action":"edit_note",...}`` object out of a fenced block, or
    None for a normal conversational reply / malformed / non-edit block."""
    match = _FENCED_JSON_RE.search(assistant_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("action") != "edit_note":
        return None
    return payload


def _apply_ops(
    note: Note, ops: list[NoteEditOp], segment_text: dict[str, str]
) -> tuple[Note, int]:
    """Apply ops onto a deep copy of the note. Returns ``(updated_note, applied)``.

    Mirrors the ``resolve_conflict`` invariants: on the first edit of a claim,
    stash ``original_text`` + set ``physician_edited``. Ops referencing an
    unknown claim / section are skipped (no crash). Added content is cited to a
    real transcript seg or recorded as a physician edit — never a fabricated
    citation.
    """
    updated = note.model_copy(deep=True)
    applied = 0
    for op in ops:
        if op.op == "reword_claim":
            claim = _find_claim(updated, op.claim_id)
            if claim is None or not (op.text and op.text.strip()):
                continue
            if not claim.physician_edited:
                claim.original_text = claim.text
            claim.text = op.text.strip()
            claim.physician_edited = True
            applied += 1
        elif op.op == "remove_claim":
            if _remove_claim(updated, op.claim_id):
                applied += 1
        elif op.op == "add_claim":
            section = _find_section(updated, op.section_id)
            if section is None or not (op.text and op.text.strip()):
                continue
            if op.source_id and op.source_id in segment_text:
                source_type = "transcript"
                source_id = op.source_id
                source_quote = segment_text[op.source_id][:_MAX_SOURCE_QUOTE]
            else:
                # Not in the transcript → physician-authored, never a fake cite.
                source_type = "physician_edit"
                source_id = f"pedit_{section.id}"
                source_quote = ""
            section.claims.append(
                NoteClaim(
                    id=f"aclaim_{uuid.uuid4().hex[:8]}",
                    text=op.text.strip(),
                    source_type=source_type,
                    source_id=source_id,
                    source_quote=source_quote,
                    physician_edited=True,
                )
            )
            if section.status == "not_captured":
                section.status = "populated"
            applied += 1
    return updated, applied


def _find_claim(note: Note, claim_id: Optional[str]):
    if not claim_id:
        return None
    for section in note.sections:
        for claim in section.claims:
            if claim.id == claim_id:
                return claim
    return None


def _find_section(note: Note, section_id: Optional[str]):
    if not section_id:
        return None
    for section in note.sections:
        if section.id == section_id:
            return section
    return None


def _remove_claim(note: Note, claim_id: Optional[str]) -> bool:
    if not claim_id:
        return False
    for section in note.sections:
        before = len(section.claims)
        section.claims = [c for c in section.claims if c.id != claim_id]
        if len(section.claims) != before:
            return True
    return False
