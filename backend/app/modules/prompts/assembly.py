"""Select the prompt text to send to the LLM.

**Replacement** semantics (CTO clarification, supersedes Phase B v1):

  * When a clinician has saved a user prompt for ``(owner_id,
    prompt_id)`` → that text is returned **alone**. The registry's
    base prompt is NOT concatenated below it.
  * When no row exists → the registry's ``system_prompt`` is returned
    verbatim as the fallback.

The naming convention (``assemble_prompt`` / ``assemble_prompt_for_
session``) is preserved so the eight consumer sites compile without
modification. The function bodies switched from concatenation to
selection — same input, same return type, different rule.

Why replacement instead of append?
  The physician is the safety reviewer of their own prompt. Asking them
  to "write a preference paragraph that goes below the system text" is
  confusing UX — they'd inevitably produce text that contradicts the
  base. Replacement gives them ONE prompt to read + sign off on, and
  pushes the descriptive-mode guarantee into the validator
  (``safety.validate_user_prompt`` requires descriptive-mode anchors
  before any row is saved).

Per-physician scope
-------------------
The row is keyed by ``(owner_id, prompt_id)``. Marie's saved prompt
never bleeds into a session where Perry is the clinician, and vice
versa. The consumer site is responsible for passing the right
``owner_id`` — which is the session's ``clinician_id`` for every
consumer in the pipeline today.

DRY / SRP — read base, read user prompt, return whichever applies.
Nothing else.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PromptOverrideModel
from app.modules.prompts.registry import PROMPTS


async def _get_user_prompt(
    db: AsyncSession,
    owner_id: uuid.UUID,
    prompt_id: str,
) -> Optional[str]:
    """Fetch the stored user prompt text for ``(owner_id, prompt_id)``.

    Returns ``None`` when no row exists. The row's
    ``user_prompt_text`` is returned verbatim — selection doesn't
    trim or re-validate; validation happened at save time and changing
    it here would create drift between what the physician saw in the
    editor preview and what the LLM actually receives.
    """
    stmt = select(PromptOverrideModel.user_prompt_text).where(
        PromptOverrideModel.owner_id == owner_id,
        PromptOverrideModel.prompt_id == prompt_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _select(base: str, user_prompt: Optional[str]) -> str:
    """Pure selector — same shape used by the preview endpoint.

    When a user prompt exists the LLM receives it standalone; otherwise
    the base prompt is the fallback. No concatenation, no separator.

    Lifted out of :func:`assemble_prompt` so the preview endpoint
    (which already has the user prompt text in hand from the request
    body or the DB row) can return the same selection without a second
    DB round-trip.
    """
    if user_prompt:
        return user_prompt
    return base


async def assemble_prompt(
    prompt_id: str,
    owner_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Return the prompt text to send to the LLM for ``owner_id``.

    Resolution (REPLACEMENT, not append):
      1. If a saved user prompt exists for ``(owner_id, prompt_id)`` →
         return it alone.
      2. Otherwise → return ``PROMPTS[prompt_id].system_prompt`` as
         the fallback.

    Raises ``KeyError`` when ``prompt_id`` is not in the registry —
    that's a programmer bug (the registry is in code) and surfacing it
    loudly is preferable to silently sending an empty prompt.

    Name kept as ``assemble_prompt`` so the eight consumer call sites
    compile unchanged. Body is now selection, not assembly.
    """
    user_prompt = await _get_user_prompt(db, owner_id, prompt_id)
    return _select(PROMPTS[prompt_id].system_prompt, user_prompt)


async def assemble_prompt_for_session(
    prompt_id: str,
    session_id: uuid.UUID | str,
    db: AsyncSession,
) -> str:
    """Variant for services that have ``session_id`` instead of
    ``owner_id`` in scope.

    Looks up the session's ``clinician_id`` and routes through
    :func:`assemble_prompt`. Returns the bare base prompt when the
    session is missing or has no ``clinician_id`` — a missing row
    never blocks the LLM call, matching the resilience pattern the
    rest of the pipeline uses.

    DRY: every consumer site that already has a ``session_id`` and a
    db session calls this instead of re-implementing the lookup. The
    eight wired sites split evenly between callers that have
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


def select_active_prompt(
    prompt_id: str,
    user_prompt_text: Optional[str],
) -> str:
    """Synchronous selector — no DB lookup.

    Used by the API's GET / PATCH response shapes to emit the
    ``active_prompt`` field without an extra DB round-trip when the
    caller already has the user prompt text (it just saved it, or
    it's pulled from the same query that produced the row).

    Returns the user prompt verbatim when set; the base prompt
    otherwise. This is the projection rule the wire schema exposes as
    ``active_prompt`` on every ``PromptResponse``.

    For an unbound caller that only has ``owner_id`` and ``prompt_id``,
    use :func:`assemble_prompt` instead — that's the one with the DB
    lookup.
    """
    return _select(PROMPTS[prompt_id].system_prompt, user_prompt_text)
