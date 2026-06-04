"""Build a small prior-context block from a clinician's prior sessions.

Single public surface: ``get_prior_context`` and its renderer
counterpart ``render_prior_context_block``. The note-gen pipeline calls
``get_prior_context`` at Stage 1 start; if it gets back a non-None
block, it renders the block via ``render_prior_context_block`` and
appends the result to the user message.

DRY/SOLID (workflow §6c):
  * ONE entry point — ``get_prior_context``.
  * ONE renderer — ``render_prior_context_block``.
  * No module imports from ``note_gen``; ``note_gen`` calls IN here.
    This is the dependency direction the architecture requires.
  * The summary dataclass (``PriorEncounterSummary``) is the single
    shared shape with the audit/render path — no parallel "summary
    for note-gen" vs "summary for audit" structures.

Per-physician scope (CLAUDE.md gate):
  Every query filters ``SessionModel.clinician_id == clinician_id``.
  Marie's prior visit with patient X never reaches Perry's session even
  when both physicians share that patient on their panels.

Descriptive-mode boundary (CLAUDE.md gate):
  ``key_claims`` is sourced from ``physical_exam`` + ``plan`` only.
  Assessment (the diagnostic impression) is deliberately dropped — see
  the module docstring on ``models.py`` for the rationale.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identifier_hash import hash_identifier
from app.core.models import NoteVersionModel, SessionModel
from app.core.types import SessionState
from app.modules.config.appconfig_client import get_config
from app.modules.longitudinal_context.models import (
    PriorContextBlock,
    PriorEncounterSummary,
)

logger = logging.getLogger("aurion.longitudinal_context")

# ── Constants ─────────────────────────────────────────────────────────────

# Max chars for the chief-complaint excerpt that lands in the rendered
# block. 200 keeps the per-encounter line compact in the LLM prompt
# (three encounters × ~200 chars = a single paragraph at the top of the
# transcript, not a wall of text) while preserving the headline
# observation. The full text never travels in this object.
_CHIEF_COMPLAINT_EXCERPT_LEN = 200

# Max chars per key-claim line. Same reasoning — keep the rendered
# block tight. Empty / short claims survive intact.
_KEY_CLAIM_LINE_LEN = 160

# Sections we summarize into ``key_claims``. Assessment is excluded by
# design (model docstring); chief-complaint has its own dedicated
# ``chief_complaint_excerpt`` slot so it isn't double-listed here.
_KEY_SECTION_IDS = ("physical_exam", "plan")

# Bounds enforced by the AppConfig schema (Pydantic side, ``ge=1``,
# ``le=10``). Re-checked here so a corrupt config can't sneak a
# zero-or-negative limit past the runtime — defends both directions.
_LIMIT_MIN = 1
_LIMIT_MAX = 10
_LIMIT_DEFAULT = 3


# ── Public API ────────────────────────────────────────────────────────────


async def get_prior_context(
    clinician_id: uuid.UUID,
    patient_identifier: str,
    current_session_id: uuid.UUID,
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
) -> Optional[PriorContextBlock]:
    """Return the last ``limit`` prior encounters for this clinician +
    identifier, excluding the current session and any PURGED rows.

    Returns:
      * ``None`` — the identifier is empty / falsy. Cold-start signal;
        the caller should skip the prior-context branch entirely.
      * ``PriorContextBlock(encounters=[], total_seen=0)`` — identifier
        is set but no prior sessions match. The caller still records
        the "looked up, found none" outcome but doesn't add a context
        line to the prompt.
      * ``PriorContextBlock(encounters=[...], total_seen=N)`` — at
        least one prior encounter was found. ``encounters`` is
        newest-first and capped at ``limit``; ``total_seen`` is the
        raw count BEFORE the cap.

    ``limit`` defaults to ``pipeline.longitudinal_context_max_encounters``
    from AppConfig (with safe bounds clamping). An explicit override is
    accepted so tests can pin a smaller number without an AppConfig
    fixture.
    """
    identifier = (patient_identifier or "").strip()
    if not identifier:
        # Identifier never set on this session → no context to load.
        # Returning None here is the explicit "cold-start" signal so the
        # caller can distinguish this from "set but no prior found".
        return None

    cap = _resolve_limit(limit)

    # Indexed lookup — see app.core.identifier_hash for the HMAC
    # rationale. Equality on the hash column is index-backed (B-tree
    # on ix_sessions_external_reference_id_hash), so the query is
    # O(log n) over the per-clinician partition.
    target_hash = hash_identifier(identifier)
    stmt = (
        select(SessionModel)
        .where(
            SessionModel.clinician_id == clinician_id,
            SessionModel.external_reference_id_hash == target_hash,
            SessionModel.id != current_session_id,
            # Exclude PURGED sessions outright — their note content is
            # gone from the DB, but the row may linger for the audit
            # trail. Trying to rehydrate them produces an empty
            # summary and confuses the model.
            SessionModel.state != SessionState.PURGED,
        )
        # Newest first — physicians think about "the last visit", so
        # the most recent encounter must lead the rendered block.
        .order_by(SessionModel.created_at.desc())
    )
    result = await db.execute(stmt)
    matching_sessions = list(result.scalars().all())

    if not matching_sessions:
        return PriorContextBlock(encounters=[], total_seen=0)

    total_seen = len(matching_sessions)
    capped = matching_sessions[:cap]

    summaries: list[PriorEncounterSummary] = []
    for session in capped:
        summary = await _summarize_session(session, db)
        if summary is not None:
            summaries.append(summary)

    return PriorContextBlock(encounters=summaries, total_seen=total_seen)


def render_prior_context_block(block: PriorContextBlock) -> str:
    """Render the block into the deterministic text shape the LLM sees.

    Output shape::

        Prior visits with this patient and this clinician (most recent first):
        - 2026-05-14 (orthopedic_surgery): "right shoulder pain x6w";
          physical_exam: ROM right flexion 140, abduction 110;
          plan: PT, follow-up 4 weeks
        - 2026-04-09 (orthopedic_surgery): ...

    Empty block (no encounters) renders to an empty string so the
    caller can unconditionally call into the renderer and concatenate
    the result. The CALLER decides whether to emit a context line at
    all based on whether the block is non-None.

    The leading header sentence is intentionally factual — it tells the
    model "these are visits you've had with this patient before" with
    no diagnostic framing. The descriptive-mode reinforcement sentence
    is appended to the SYSTEM prompt at call time by ``note_gen``, not
    here; this renderer is just the data presenter.
    """
    if not block.encounters:
        return ""

    lines: list[str] = [
        "Prior visits with this patient and this clinician (most recent first):",
    ]
    for enc in block.encounters:
        lines.append(_format_encounter_line(enc))
    return "\n".join(lines)


# ── Internals ─────────────────────────────────────────────────────────────


def _resolve_limit(explicit_override: Optional[int]) -> int:
    """Resolve the per-call limit with AppConfig as the source of truth.

    Order:
      1. Explicit ``limit=...`` kwarg (tests, future feature toggles).
      2. ``pipeline.longitudinal_context_max_encounters`` from AppConfig.
      3. Hard-coded fallback ``_LIMIT_DEFAULT=3`` when AppConfig load
         itself fails — never block Stage 1 over a config blip.

    Result is clamped to ``[_LIMIT_MIN, _LIMIT_MAX]`` so a tampered
    config can't blow up the query.
    """
    if explicit_override is not None:
        return max(_LIMIT_MIN, min(_LIMIT_MAX, explicit_override))
    try:
        cfg = get_config()
        candidate = cfg.pipeline.longitudinal_context_max_encounters
    except Exception:  # noqa: BLE001 — defensive against any AppConfig hiccup
        logger.warning(
            "AppConfig pipeline.longitudinal_context_max_encounters unavailable "
            "— falling back to default %d",
            _LIMIT_DEFAULT,
        )
        return _LIMIT_DEFAULT
    return max(_LIMIT_MIN, min(_LIMIT_MAX, candidate))


async def _summarize_session(
    session: SessionModel,
    db: AsyncSession,
) -> Optional[PriorEncounterSummary]:
    """Load the prior session's latest note and roll it into a summary.

    Returns ``None`` only on hard rehydration failures (corrupt note
    JSON in the column, etc.) — those are logged + skipped so one bad
    row never blocks the whole prior-context load. A session that
    simply has no note yields a summary with no chief-complaint /
    claims, which is still useful context ("you saw this patient on
    YYYY-MM-DD for ${specialty}").
    """
    note_version = await _get_latest_note_version(session.id, db)
    chief_complaint = None
    key_claims: list[str] = []

    if note_version is not None:
        try:
            content = json.loads(note_version.content)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Skipping prior-context summarization for session=%s "
                "(invalid note JSON): %s",
                session.id,
                exc,
            )
            return PriorEncounterSummary(
                session_id=session.id,
                date=session.created_at.date(),
                specialty=session.specialty,
                chief_complaint_excerpt=None,
                key_claims=[],
            )

        chief_complaint = _extract_chief_complaint(content)
        key_claims = _extract_key_claims(content)

    return PriorEncounterSummary(
        session_id=session.id,
        date=session.created_at.date(),
        specialty=session.specialty,
        chief_complaint_excerpt=chief_complaint,
        key_claims=key_claims,
    )


async def _get_latest_note_version(
    session_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[NoteVersionModel]:
    """Latest note version (any stage) for the session.

    Not routed through ``note_gen.repository`` to keep the dependency
    arrow pointing the right way: ``note_gen`` calls into
    ``longitudinal_context``, not the reverse. The query is small +
    indexed on ``session_id`` so duplicating it here costs nothing.
    """
    stmt = (
        select(NoteVersionModel)
        .where(NoteVersionModel.session_id == session_id)
        .order_by(NoteVersionModel.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _extract_chief_complaint(note_content: dict) -> Optional[str]:
    """Pull the chief-complaint section's first claim text from a note
    JSON blob and truncate to the excerpt length.

    Returns ``None`` when the section is missing / empty so the
    rendered line can fall back to "(no chief complaint recorded)"
    cleanly upstream.
    """
    for section in note_content.get("sections", []):
        if section.get("id") != "chief_complaint":
            continue
        claims = section.get("claims") or []
        if not claims:
            return None
        text = (claims[0].get("text") or "").strip()
        if not text:
            return None
        return _truncate(text, _CHIEF_COMPLAINT_EXCERPT_LEN)
    return None


def _extract_key_claims(note_content: dict) -> list[str]:
    """Pull physical_exam + plan section claims and roll each into a
    single-line, truncated string.

    ``assessment`` is deliberately NOT in ``_KEY_SECTION_IDS`` — the
    prior physician's diagnostic impression must not be fed back into
    the model on the next visit.
    """
    out: list[str] = []
    for section in note_content.get("sections", []):
        section_id = section.get("id")
        if section_id not in _KEY_SECTION_IDS:
            continue
        claims = section.get("claims") or []
        if not claims:
            continue
        # Roll all claim texts into one comma-separated line per
        # section. Empty / whitespace claims are dropped.
        joined = "; ".join(
            (c.get("text") or "").strip()
            for c in claims
            if (c.get("text") or "").strip()
        )
        if not joined:
            continue
        out.append(f"{section_id}: {_truncate(joined, _KEY_CLAIM_LINE_LEN)}")
    return out


def _format_encounter_line(enc: PriorEncounterSummary) -> str:
    """Format one encounter into the bullet-line shape the renderer
    emits. Pure function so the same shape is testable without
    exercising the whole pipeline."""
    parts: list[str] = [f"- {enc.date.isoformat()} ({enc.specialty}):"]
    if enc.chief_complaint_excerpt:
        parts.append(f' "{enc.chief_complaint_excerpt}";')
    else:
        parts.append(" (no chief complaint recorded);")
    if enc.key_claims:
        parts.append(" " + "; ".join(enc.key_claims))
    return "".join(parts)


def _truncate(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len`` chars, appending an ellipsis
    when shortened. Whitespace at the cut point is trimmed so the
    truncation never produces "foo …" with a hanging space."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"
