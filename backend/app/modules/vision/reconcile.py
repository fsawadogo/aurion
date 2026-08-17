"""Stage 2 caption reconciliation (Tier 1 / item C).

Replaces the previous "trust the vision provider's integration_status"
shortcut. The vision provider captions each frame in isolation — it has
no idea what the Stage 1 note claimed for the same moment. So
ENRICHES/REPEATS/CONFLICTS came back as a guess, not a real comparison.

This module does the real comparison: one LLM call that sees the Stage
1 note (claims + source quotes) plus every caption (description +
audio-anchor) and returns per-caption status grounded in actual
reconciliation. Result: the CONFLICTS flag actually means something —
which matters because CLAUDE.md's pilot success criterion is
"CONFLICTS resolution: 100% resolved before approval".

Implementation: Anthropic Sonnet via tool_use for schema-enforced
output. Falls back to no-op (preserves existing integration_status)
on any failure so an outage in the reconciler never breaks Stage 2.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import FrameCaption, Note

logger = logging.getLogger("aurion.vision.reconcile")

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"
_ENDPOINT = "https://api.anthropic.com/v1/messages"


# Promoted to a module-level public constant (was ``_RECONCILE_SYSTEM_PROMPT``)
# so the AI Prompts Transparency registry (``app.modules.prompts``) can import
# it as the single source of truth. No copy-paste between this module and the
# registry — the registry imports this exact string. Phase A read-only;
# Phase B replaces with per-physician text when the calling clinician
# has saved a user prompt (replacement semantics).
RECONCILE_SYSTEM_PROMPT = """You reconcile clinical visual observations with what was said and with the other visual observations from the same encounter.

Compare every caption with both the audio-derived claims and the other captions, including captions at nearby or different anchors that concern the same clinical finding:
- ENRICHES — the visual adds supported, clinically useful information not already captured by the audio or by another retained visual caption.
- REPEATS — the visual confirms the audio with no added finding, duplicates or closely restates another caption, or contains only acquisition/view metadata without a clinical finding. For duplicate visual observations, retain at most the single best-supported, most specific concise caption as ENRICHES and mark the others REPEATS.
- CONFLICTS — the visual contradicts an audio claim or another visual caption (e.g. disagreement about presence, severity, location, or laterality). If the evidence does not clearly resolve a visual-to-visual disagreement, mark the conflicting captions CONFLICTS and briefly identify the disagreement.

Compare LITERALLY. Do not infer clinical meaning. If the audio is silent on something the frame shows, that is ENRICHES.
If the frame is too generic to compare (low signal, equipment-only, anatomy inventory, viewer thumbnails, or image-quality commentary), classify as REPEATS so it doesn't pollute the note.

For every ENRICHES decision, also return note_text: exactly one concise, note-ready clinical sentence derived solely from that frame's visual caption. Start with the supported finding, not the acquisition medium or patient position. You may remove scene narration and tighten wording, but do not add or strengthen a fact, import a fact from the audio, or combine evidence from another frame. If the frame's caption cannot support such a sentence, classify it as REPEATS and return an empty note_text.

Return only the requested tool call."""


_RECONCILE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frame_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["ENRICHES", "REPEATS", "CONFLICTS"],
                    },
                    "note_text": {
                        "type": "string",
                        "description": (
                            "For ENRICHES: exactly one concise clinical sentence "
                            "derived only from this frame's visual caption. Empty "
                            "for REPEATS and CONFLICTS."
                        ),
                    },
                    "conflict_detail": {"type": "string"},
                },
                "required": ["frame_id", "status", "note_text"],
            },
        }
    },
    "required": ["decisions"],
}


def _build_user_prompt(note: Note, captions: list[FrameCaption]) -> str:
    """Render the note's claims + every caption into a single comparison
    prompt. Keep it terse — the model just needs the audio→frame mapping
    and the claims that share an anchor segment."""
    # Group claims by their transcript source_id so the model can match
    # them to captions sharing an audio_anchor_id.
    by_anchor: dict[str, list[str]] = {}
    for section in note.sections:
        for claim in section.claims:
            if claim.source_type == "transcript" and claim.source_id:
                by_anchor.setdefault(claim.source_id, []).append(
                    f'  - [{section.id}] {claim.text}  (source quote: "{claim.source_quote}")'
                )

    captions_block: list[str] = []
    for cap in captions:
        anchor_claims = by_anchor.get(cap.audio_anchor_id, [])
        anchor_summary = "\n".join(anchor_claims) if anchor_claims else "  (no audio claims anchored to this moment)"
        captions_block.append(
            f"FRAME {cap.frame_id} (anchored to {cap.audio_anchor_id}, "
            f"confidence={cap.confidence}):\n"
            f'  visual: "{cap.visual_description}"\n'
            f"  audio claims at the same moment:\n{anchor_summary}\n"
        )

    return (
        "Classify each frame against the audio claims and all other visual captions. "
        "Keep only non-duplicative, supported clinical enrichment. For every ENRICHES "
        "decision, return note_text as one note-ready clinical sentence based only on "
        "that frame's visual text; never import facts from the audio or another frame.\n\n" + "\n".join(captions_block)
    )


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_ACQUISITION_NARRATION_OPENER = re.compile(
    r"^(?:(?:a|an|the)\s+)?(?:image|frame|photo|photograph|picture|video|clip|"
    r"still|monitor|screen|subject)\b",
    re.IGNORECASE,
)


def _note_ready_sentence(value: object) -> str | None:
    """Return one chart-ready sentence, or ``None`` for scene narration."""

    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or _ACQUISITION_NARRATION_OPENER.search(text):
        return None
    sentences = [sentence for sentence in _SENTENCE_BOUNDARY.split(text) if sentence]
    return text if len(sentences) == 1 else None


async def reconcile_captions(
    captions: list[FrameCaption],
    note: Note,
    system_prompt: Optional[str] = None,
    *,
    db: Optional[AsyncSession] = None,
    session_id: Optional[str] = None,
) -> list[FrameCaption]:
    """Reconcile visual captions against the Stage 1 note via a single
    LLM call. Returns the same captions with ``integration_status`` and
    ``conflict_flag`` / ``conflict_detail`` updated based on the real
    comparison.

    Best-effort: any failure (no API key, HTTP error, malformed
    response) logs a warning and returns the captions unchanged so
    Stage 2 still produces a usable note.

    ``system_prompt`` (AI-PROMPTS-B) — when set, used as the system
    instruction instead of the bare ``RECONCILE_SYSTEM_PROMPT``
    constant. Service layer selects either the per-physician
    REPLACEMENT user prompt or the registry default via
    ``app.modules.prompts.assemble_prompt``. ``None`` preserves
    pre-Phase-B behaviour.
    """
    if not captions:
        return captions

    if not _ANTHROPIC_API_KEY:
        logger.warning(
            "reconcile: ANTHROPIC_API_KEY not configured — leaving provider-reported integration_status unchanged"
        )
        return captions

    user_prompt = _build_user_prompt(note, captions)
    # AI-PROMPTS-B — assembled prompt or base constant.
    effective_system = system_prompt or RECONCILE_SYSTEM_PROMPT

    _started = time.monotonic()
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
                    "max_tokens": 2000,
                    "temperature": 0.1,
                    "system": effective_system,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "tools": [
                        {
                            "name": "emit_reconciliation",
                            "description": (
                                "Emit per-frame ENRICHES/REPEATS/CONFLICTS "
                                "decisions based on a literal comparison "
                                "with the audio claims."
                            ),
                            "input_schema": _RECONCILE_SCHEMA,
                        }
                    ],
                    "tool_choice": {
                        "type": "tool",
                        "name": "emit_reconciliation",
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        # Telemetry: count this (registry-bypassing) Stage-2 Claude call so
        # per-session token/cost is complete. Best-effort — never blocks Stage 2.
        if db is not None:
            from app.modules.providers.usage_service import record_offline_call

            usage = data.get("usage") or {}
            await record_offline_call(
                db,
                provider_type="note_generation",
                provider_name="anthropic",
                model=_MODEL,
                operation="reconcile_captions",
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                latency_ms=int((time.monotonic() - _started) * 1000),
                session_id=uuid.UUID(session_id) if session_id else None,
            )

        decisions_payload: dict | None = None
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "emit_reconciliation":
                decisions_payload = block["input"]
                break
        if decisions_payload is None:
            for block in data.get("content", []):
                if "text" in block:
                    decisions_payload = json.loads(block["text"])
                    break
        if decisions_payload is None:
            logger.warning("reconcile: no tool_use or text in response — preserving original integration_status")
            return captions
    except Exception:  # noqa: BLE001 — best-effort by design
        logger.warning("reconcile: LLM call failed — preserving original integration_status", exc_info=True)
        return captions

    decision_by_frame: dict[str, dict] = {
        d["frame_id"]: d for d in decisions_payload.get("decisions", []) if "frame_id" in d
    }

    for cap in captions:
        decision = decision_by_frame.get(cap.frame_id)
        if not decision:
            continue
        new_status = decision.get("status")
        if new_status in {"ENRICHES", "REPEATS", "CONFLICTS"}:
            cap.integration_status = new_status
        if new_status == "ENRICHES":
            # Prefer the reconciler's chart-ready wording. A pre-existing
            # single-sentence caption remains a compatibility fallback for
            # custom prompts or older responses. Paragraph-shaped scene
            # descriptions fail closed as REPEATS instead of entering the note.
            note_text = _note_ready_sentence(decision.get("note_text"))
            note_text = note_text or _note_ready_sentence(cap.visual_description)
            if note_text is None:
                cap.integration_status = "REPEATS"
                cap.conflict_flag = False
                cap.conflict_detail = None
                continue
            cap.visual_description = note_text
        if new_status == "CONFLICTS":
            cap.conflict_flag = True
            detail = decision.get("conflict_detail")
            if isinstance(detail, str) and detail:
                cap.conflict_detail = detail
        else:
            cap.conflict_flag = False
            cap.conflict_detail = None

    enriches = sum(1 for c in captions if c.integration_status == "ENRICHES")
    repeats = sum(1 for c in captions if c.integration_status == "REPEATS")
    conflicts = sum(1 for c in captions if c.conflict_flag)
    logger.info(
        "reconcile: enriches=%d repeats=%d conflicts=%d (of %d captions)",
        enriches,
        repeats,
        conflicts,
        len(captions),
    )
    return captions
