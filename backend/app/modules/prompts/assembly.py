"""Assemble the final prompt text for an LLM call.

Single DRY source of prompt assembly. Every consumer site that needs
the physician-customized version of a system prompt calls
``assemble_prompt(prompt_id, owner_id, db)`` here — providers never
construct their own combined string.

Architecture
------------
The base prompt is the descriptive-mode safety boundary (CLAUDE.md
"Single Most Important Constraint"). It MUST NOT be modified at
runtime. The physician's overlay is appended below a clear separator
so the LLM treats it as physician preferences, not as an instruction
that overrides the base rules:

    {base}

    --- Physician preferences ---
    {overlay}

When no overlay exists for the (owner_id, prompt_id) pair, the base
prompt is returned verbatim — no separator, no trailing whitespace
change. This keeps the behaviour identical to the pre-Phase-B path
for any physician who hasn't customized anything.

Per-physician scope
-------------------
The overlay row is keyed by (owner_id, prompt_id). Marie's overlay
never bleeds into a session where Perry is the clinician, and vice
versa. The consumer site is responsible for passing the right
``owner_id`` — which is the session's ``clinician_id`` for every
consumer in the pipeline today.

DRY / SRP — read base + read overlay + join. Nothing else.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PromptOverrideModel
from app.modules.prompts.registry import PROMPTS

#: Separator the overlay is joined below. Chosen so the LLM treats the
#: tail as physician preferences rather than as a competing system
#: instruction. The phrasing is human-readable for the sandbox preview
#: too.
OVERLAY_SEPARATOR: str = "--- Physician preferences ---"


async def _get_owner_overlay(
    db: AsyncSession,
    owner_id: uuid.UUID,
    prompt_id: str,
) -> Optional[str]:
    """Fetch the stored overlay text for ``(owner_id, prompt_id)``.

    Returns ``None`` when no row exists. The row's ``overlay_text`` is
    returned verbatim — assembly doesn't trim or re-validate; the
    validation happened at save time and changing it here would create
    drift between what the physician saw in the editor preview and
    what the LLM actually receives.
    """
    stmt = select(PromptOverrideModel.overlay_text).where(
        PromptOverrideModel.owner_id == owner_id,
        PromptOverrideModel.prompt_id == prompt_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row


def _combine(base: str, overlay: Optional[str]) -> str:
    """Pure join function — same shape used by the sandbox preview.

    Lifted out of :func:`assemble_prompt` so the preview endpoint
    (which already has the overlay text in hand from the request body)
    can call the same join without a DB round-trip.
    """
    if not overlay:
        return base
    return f"{base}\n\n{OVERLAY_SEPARATOR}\n{overlay}"


async def assemble_prompt(
    prompt_id: str,
    owner_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Return the prompt text that should be sent to the LLM.

    Looks up the base prompt by ``prompt_id`` in the registry, then
    appends the per-owner overlay if one exists. Owner scope is strict:
    a different physician's overlay can never appear in this caller's
    assembled prompt.

    Raises ``KeyError`` when ``prompt_id`` is not in the registry —
    that's a programmer bug (the registry is in code), and surfacing
    it loudly is preferable to silently sending an empty prompt.
    """
    base = PROMPTS[prompt_id].system_prompt
    overlay = await _get_owner_overlay(db, owner_id, prompt_id)
    return _combine(base, overlay)


async def assemble_prompt_for_session(
    prompt_id: str,
    session_id: uuid.UUID | str,
    db: AsyncSession,
) -> str:
    """Variant for services that have ``session_id`` instead of
    ``owner_id`` in scope.

    Looks up the session's ``clinician_id`` and routes through
    :func:`assemble_prompt`. Returns the bare base prompt when the
    session isn't found — a missing row never blocks the LLM call,
    matching the resilience pattern the rest of the pipeline uses.

    DRY: every consumer site that already has a ``session_id`` and a
    db session calls this instead of re-implementing the lookup. The
    8 wired sites split evenly between callers that have
    ``owner_id`` (clinician routes — patient summary, orders, coding,
    live preview) and callers that only have ``session_id`` (Stage 1
    note generation, Stage 2 vision).
    """
    # Local import to avoid a circular dependency on app.core.models
    # when prompts/__init__ is loaded during app startup. Importing at
    # function scope keeps the module's top-level clean.
    from sqlalchemy import select

    from app.core.models import SessionModel

    try:
        sid = (
            session_id
            if isinstance(session_id, uuid.UUID)
            else uuid.UUID(str(session_id))
        )
    except (ValueError, AttributeError):
        return PROMPTS[prompt_id].system_prompt
    result = await db.execute(
        select(SessionModel.clinician_id).where(SessionModel.id == sid)
    )
    clinician_id = result.scalar_one_or_none()
    if clinician_id is None:
        return PROMPTS[prompt_id].system_prompt
    return await assemble_prompt(prompt_id, clinician_id, db)


def assemble_preview(
    prompt_id: str,
    overlay_text: Optional[str],
) -> str:
    """Synchronous preview-time join — no DB lookup.

    Used by the API's GET / PATCH response shapes to emit the
    ``assembled_preview`` field without an extra DB round-trip when
    the caller already has the overlay (it just saved it, or it's
    pulled from the same query that produced the row).

    For an unbound caller that only has ``owner_id`` and ``prompt_id``,
    use :func:`assemble_prompt` instead — that's the one with the DB
    lookup.
    """
    base = PROMPTS[prompt_id].system_prompt
    return _combine(base, overlay_text)
