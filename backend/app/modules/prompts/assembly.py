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
from collections import defaultdict
from datetime import datetime
from typing import NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import PromptOverrideModel
from app.core.types import PublicationScope
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


def _select_published_index(
    keys: list[tuple[str, Optional[uuid.UUID], Optional[str]]],
    owner_id: uuid.UUID,
    role_value: Optional[str],
) -> Optional[int]:
    """Index of the winning publication by scope specificity (PS-02).

    ``keys`` are the routing columns of the ACTIVE publications for one job,
    each ``(scope, target_user_id, target_role)``, ordered newest-first.
    Precedence, most specific first: ``SELF`` (matching ``owner_id``) → ``ROLE``
    (matching ``role_value``) → ``ALL``. Returns the index of the most specific
    match, or ``None`` when nothing applies.

    Pure (no DB) and the single home of the PS-02 precedence rule — shared by
    the note-gen text path (:func:`_select_published`) and the visibility
    metadata path (:func:`get_active_publications_for`), so the two can never
    drift on which publication "wins".
    """
    for i, (scope, target_user_id, _role) in enumerate(keys):
        if scope == PublicationScope.SELF.value and target_user_id == owner_id:
            return i
    if role_value is not None:
        for i, (scope, _user, target_role) in enumerate(keys):
            if scope == PublicationScope.ROLE.value and target_role == role_value:
                return i
    for i, (scope, _user, _role) in enumerate(keys):
        if scope == PublicationScope.ALL.value:
            return i
    return None


def _select_published(
    rows: list[tuple[str, Optional[uuid.UUID], Optional[str], str]],
    owner_id: uuid.UUID,
    role_value: Optional[str],
) -> Optional[str]:
    """Winning publication TEXT by scope specificity (PS-02).

    Thin wrapper over :func:`_select_published_index`: ``rows`` are
    ``(scope, target_user_id, target_role, version_text)``; returns the winner's
    text or ``None``. The note-gen entry point — the precedence rule itself
    lives in :func:`_select_published_index`.
    """
    idx = _select_published_index(
        [(scope, tu, tr) for scope, tu, tr, _text in rows], owner_id, role_value
    )
    return rows[idx][3] if idx is not None else None


async def _get_published_prompt(
    db: AsyncSession,
    owner_id: uuid.UUID,
    prompt_id: str,
) -> Optional[str]:
    """Text of the active admin-published prompt for this clinician's cohort
    and job, or ``None`` (PS-02).

    Reads the ACTIVE publications (``superseded_at IS NULL``) for
    ``job_id == prompt_id``, newest first, joins each to its version's text,
    then applies :func:`_select_published`. Only reached when the clinician has
    no personal override of their own — the override wins in
    :func:`assemble_prompt` before this runs.

    Models are imported at function scope, matching the
    :func:`assemble_prompt_for_session` pattern below, to keep
    ``app.core.models`` off the ``prompts`` package import path at app startup.
    """
    from app.core.models import (
        PromptPublicationModel,
        StudioPromptVersionModel,
        UserModel,
    )

    role = (
        await db.execute(select(UserModel.role).where(UserModel.id == owner_id))
    ).scalar_one_or_none()
    rows = (
        await db.execute(
            select(
                PromptPublicationModel.scope,
                PromptPublicationModel.target_user_id,
                PromptPublicationModel.target_role,
                StudioPromptVersionModel.text,
            )
            .join(
                StudioPromptVersionModel,
                PromptPublicationModel.version_id == StudioPromptVersionModel.id,
            )
            .where(
                PromptPublicationModel.job_id == prompt_id,
                PromptPublicationModel.superseded_at.is_(None),
            )
            .order_by(PromptPublicationModel.published_at.desc())
        )
    ).all()
    if not rows:
        return None
    role_value = role.value if role is not None else None
    return _select_published(list(rows), owner_id, role_value)


class PublishedPromptMeta(NamedTuple):
    """Display metadata for the active admin publication applying to a clinician
    for one job — the visibility surface's counterpart to the note-gen text.
    Never carries the prompt text."""

    name: str
    version_no: int
    scope: str
    target_role: Optional[str]
    published_at: datetime


async def get_active_publications_for(
    db: AsyncSession,
    owner_id: uuid.UUID,
    prompt_ids: list[str],
) -> dict[str, PublishedPromptMeta]:
    """Active admin-publication metadata applying to ``owner_id``, keyed by job.

    Resolves the SAME ``SELF → ROLE → ALL`` precedence as note-gen
    (:func:`_select_published`, via :func:`_select_published_index`) but returns
    DISPLAY metadata (name, version, scope, date) instead of text — for the AI
    Prompts Transparency banner so a clinician can SEE the prompt an admin
    shared.

    Deliberately does NOT short-circuit on a personal override (unlike
    :func:`assemble_prompt`): the banner shows the publication even when the
    clinician's own override shadows it at runtime. The caller pairs this with
    ``is_overridden`` to message the shadow.

    One role lookup + one publications query for all ``prompt_ids`` (no N+1);
    returns only jobs that have an applicable active publication.
    """
    from app.core.models import (
        PromptPublicationModel,
        StudioPromptModel,
        StudioPromptVersionModel,
        UserModel,
    )

    if not prompt_ids:
        return {}
    role = (
        await db.execute(select(UserModel.role).where(UserModel.id == owner_id))
    ).scalar_one_or_none()
    role_value = role.value if role is not None else None

    rows = (
        await db.execute(
            select(
                PromptPublicationModel.job_id,
                PromptPublicationModel.scope,
                PromptPublicationModel.target_user_id,
                PromptPublicationModel.target_role,
                StudioPromptModel.name,
                StudioPromptVersionModel.version_no,
                PromptPublicationModel.published_at,
            )
            .join(
                StudioPromptVersionModel,
                PromptPublicationModel.version_id == StudioPromptVersionModel.id,
            )
            .join(
                StudioPromptModel,
                StudioPromptVersionModel.studio_prompt_id == StudioPromptModel.id,
            )
            .where(
                PromptPublicationModel.job_id.in_(prompt_ids),
                PromptPublicationModel.superseded_at.is_(None),
            )
            .order_by(PromptPublicationModel.published_at.desc())
        )
    ).all()

    by_job: dict[str, list] = defaultdict(list)
    for row in rows:
        by_job[row.job_id].append(row)

    resolved: dict[str, PublishedPromptMeta] = {}
    for job_id, job_rows in by_job.items():
        keys = [(r.scope, r.target_user_id, r.target_role) for r in job_rows]
        idx = _select_published_index(keys, owner_id, role_value)
        if idx is not None:
            winner = job_rows[idx]
            resolved[job_id] = PublishedPromptMeta(
                name=winner.name,
                version_no=winner.version_no,
                scope=winner.scope,
                target_role=winner.target_role,
                published_at=winner.published_at,
            )
    return resolved


async def assemble_prompt(
    prompt_id: str,
    owner_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Return the prompt text to send to the LLM for ``owner_id``.

    Resolution order (most specific first), all REPLACEMENT (no append):
      1. The clinician's own saved user prompt for ``(owner_id, prompt_id)``
         → returned alone. Unchanged from Phase B.
      2. The active admin **publication** for this job that targets the
         clinician — ``SELF`` → ``ROLE`` → ``ALL`` (PS-02). This is how a
         prompt an admin authored + shared takes effect for clinicians who
         haven't overridden it.
      3. The registry default ``PROMPTS[prompt_id].system_prompt``.

    A personal override (1) always outranks an admin publication (2): a
    physician who has signed off on their own prompt keeps it; a clinic-wide
    change reaches only physicians who haven't.

    Raises ``KeyError`` when ``prompt_id`` is not in the registry — a
    programmer bug (the registry is in code). Checked up front so an unknown
    id fails loud regardless of any stored override or publication, rather
    than silently sending unvetted text to the LLM (defence in depth on the
    descriptive-mode boundary: a publication for a non-registry job must never
    reach the model).

    Name kept as ``assemble_prompt`` so the eight consumer call sites compile
    unchanged.
    """
    if prompt_id not in PROMPTS:
        raise KeyError(prompt_id)
    user_prompt = await _get_user_prompt(db, owner_id, prompt_id)
    if user_prompt:
        return user_prompt
    published = await _get_published_prompt(db, owner_id, prompt_id)
    if published is not None:
        return published
    return PROMPTS[prompt_id].system_prompt


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

    Scope note (PS-02): this projection deliberately knows only the
    per-physician override vs. the registry default — NOT admin
    publications. A publication is an admin→clinician delivery mechanism
    resolved in :func:`assemble_prompt`; it does not surface in the
    clinician's transparency view, which shows what the physician
    themselves saved or the shipped default. Revisit only if a future
    feature makes publications clinician-visible.

    For an unbound caller that only has ``owner_id`` and ``prompt_id``,
    use :func:`assemble_prompt` instead — that's the one with the DB
    lookup.
    """
    return _select(PROMPTS[prompt_id].system_prompt, user_prompt_text)
