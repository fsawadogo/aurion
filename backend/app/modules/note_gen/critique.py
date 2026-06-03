"""Stage 1 self-critique pass (Tier 1 / item D).

After Stage 1 produces a note, run a cheap second LLM call asking the
model to review its own work for the most common mistakes:

  - Claims with empty / missing source_id (unanchored — should be dropped).
  - Sections marked "populated" with no claims (should flip to
    "not_captured" or "pending_video").
  - Sections marked "populated" where the only claims have source_quotes
    that don't actually support the claim text (hallucinated paraphrase).
  - Sections marked "not_captured" that the transcript actually covers
    (missed content — flagged but NOT auto-corrected; physician decides).

Best-effort: any failure (no API key, HTTP error, malformed response)
logs a warning and returns the original note unchanged. Stage 1 SLA
(<30s) is preserved because the critique runs in series after generation
but typically completes in <2s for small notes (the critique payload
is the note itself plus a transcript reference, no rebuild).
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from app.core.types import Note, Transcript

logger = logging.getLogger("aurion.note_gen.critique")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"
_ENDPOINT = "https://api.anthropic.com/v1/messages"


# Promoted to a module-level public constant (was ``_CRITIQUE_SYSTEM_PROMPT``)
# so the AI Prompts Transparency registry (``app.modules.prompts``) can import
# it as the single source of truth. The critic runs on Stage 1 notes before
# the physician sees them; its instructions are part of the safety surface
# physicians can audit on the portal Transparency page.
CRITIQUE_SYSTEM_PROMPT = """You audit a clinical note for traceability + correctness mistakes before a physician sees it.

For each potential issue, return a structured fix. The auditor MAY mutate the note via these actions:
- "drop_claim": remove a claim whose source_id is missing/empty or whose source_quote doesn't support its text.
- "set_section_status": flip a section's status (e.g. populated → not_captured if it has zero claims; populated → pending_video if it depends on visual capture).

Do NOT add new claims. Do NOT rephrase claim text. Do NOT change source_ids. Your role is conservative cleanup, not rewriting.

Be specific: every action must name the section_id (and claim_id for drop_claim) plus a one-line reason. If nothing needs fixing, return an empty actions array."""


_CRITIQUE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["drop_claim", "set_section_status"],
                    },
                    "section_id": {"type": "string"},
                    "claim_id": {"type": "string"},
                    "new_status": {
                        "type": "string",
                        "enum": ["populated", "pending_video", "not_captured"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["action", "section_id", "reason"],
            },
        }
    },
    "required": ["actions"],
}


def _build_critique_prompt(note: Note, transcript: Transcript) -> str:
    """Render the note + transcript-segment-id list so the critic can
    verify each claim's source_id maps to a real segment."""
    valid_segment_ids = {s.id for s in transcript.segments}
    note_dump: list[str] = []
    for section in note.sections:
        note_dump.append(
            f"SECTION {section.id} (status={section.status}):"
        )
        if not section.claims:
            note_dump.append("  (no claims)")
        for claim in section.claims:
            anchor_ok = claim.source_id in valid_segment_ids
            note_dump.append(
                f"  - {claim.id} [src={claim.source_id} valid={anchor_ok}]: "
                f'"{claim.text}"  '
                f'(source_quote: "{claim.source_quote or ""}")'
            )
    return (
        f"Valid transcript segment IDs: {sorted(valid_segment_ids)}\n\n"
        + "NOTE TO AUDIT:\n"
        + "\n".join(note_dump)
        + "\n\nReturn the actions array via the emit_critique tool."
    )


async def critique_note(note: Note, transcript: Transcript) -> Note:
    """Audit + apply conservative fixes to a Stage 1 note.

    Returns the same Note object, mutated in place. Best-effort: any
    failure preserves the original note unchanged.
    """
    if not _ANTHROPIC_API_KEY:
        logger.info("critique: ANTHROPIC_API_KEY not set — skipping")
        return note
    if not note.sections:
        return note

    user_prompt = _build_critique_prompt(note, transcript)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                _ENDPOINT,
                headers={
                    "x-api-key": _ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "max_tokens": 1500,
                    "temperature": 0.1,
                    "system": CRITIQUE_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "tools": [
                        {
                            "name": "emit_critique",
                            "description": (
                                "Emit conservative cleanup actions for "
                                "the Stage 1 note (drop unanchored claims, "
                                "flip section statuses)."
                            ),
                            "input_schema": _CRITIQUE_SCHEMA,
                        }
                    ],
                    "tool_choice": {
                        "type": "tool",
                        "name": "emit_critique",
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        payload: dict | None = None
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "emit_critique":
                payload = block["input"]
                break
        if payload is None:
            for block in data.get("content", []):
                if "text" in block:
                    payload = json.loads(block["text"])
                    break
        if payload is None:
            logger.warning("critique: no tool_use or text — leaving note unchanged")
            return note
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("critique: LLM call failed — leaving note unchanged", exc_info=True)
        return note

    applied = _apply_actions(note, payload.get("actions", []))
    logger.info(
        "critique: applied %d action(s) to %d section(s)",
        applied, len(note.sections),
    )
    return note


def _apply_actions(note: Note, actions: list[dict]) -> int:
    """Mutate ``note`` per the auditor's actions. Returns the number of
    actions that landed. Unknown sections / claims are silently skipped
    (defensive against the model hallucinating an id)."""
    section_by_id = {s.id: s for s in note.sections}
    applied = 0

    for action in actions:
        section_id = action.get("section_id")
        section = section_by_id.get(section_id)
        if not section:
            continue

        kind = action.get("action")
        if kind == "drop_claim":
            claim_id = action.get("claim_id")
            before = len(section.claims)
            section.claims = [c for c in section.claims if c.id != claim_id]
            if len(section.claims) < before:
                applied += 1
                logger.info(
                    "critique drop_claim: section=%s claim=%s reason=%s",
                    section_id, claim_id, action.get("reason", ""),
                )

        elif kind == "set_section_status":
            new_status = action.get("new_status")
            if new_status in {"populated", "pending_video", "not_captured"}:
                if section.status != new_status:
                    section.status = new_status
                    applied += 1
                    logger.info(
                        "critique set_section_status: section=%s -> %s reason=%s",
                        section_id, new_status, action.get("reason", ""),
                    )

    return applied
