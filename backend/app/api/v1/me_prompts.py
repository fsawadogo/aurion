"""Self-scoped AI Prompts Transparency endpoints.

Phase A (read-only) + Phase B (per-physician REPLACEMENT user prompts).

The GET path lists every LLM system prompt the encounter pipeline uses
plus the calling physician's saved user prompt (or ``None``) and
``active_prompt`` — the actual text the LLM would receive for THIS
physician's next call. PATCH saves / updates a user prompt; DELETE
removes it (falling back to the registry default).

Why a separate router (not folded into ``me.py``)?
  * ``me.py`` is gated CLINICIAN-only at the router level. The GET path
    here is intentionally readable by ADMIN / EVAL_TEAM /
    COMPLIANCE_OFFICER too — support roles need visibility into the
    safety surface.
  * The PATCH / DELETE paths ARE CLINICIAN-only (no physician proxy on
    their behalf). Mounting them in this same file keeps the prompt
    feature contained in one place; the role gating is per-endpoint
    via the dependency in ``Depends(...)``.

Replacement semantics (CTO clarification, supersedes PR #227 v1)
----------------------------------------------------------------
When a clinician saves text it REPLACES the registry's system prompt
for their own sessions. The registry text is the fallback used only
when no row exists for that ``(clinician_id, prompt_id)`` pair. The
validator (``validate_user_prompt``) requires descriptive-mode anchor
language in the saved text — without it, replacement would silently
strip the descriptive-mode boundary CLAUDE.md mandates. That check is
the single thing standing between physician input and the LLM.

Audit invariants
----------------
- Every PATCH writes ``PROMPT_USER_PROMPT_SET`` with kwargs
  ``{actor_id, prompt_id, user_prompt_length}`` — never the text.
- Every DELETE writes ``PROMPT_USER_PROMPT_CLEARED`` with
  ``{actor_id, prompt_id}``.
- Both events use the synthetic session id
  ``00000000-0000-0000-0000-000000000000`` because the row is
  per-physician, not per-session.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import PromptOverrideModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.prompts import (
    PROMPTS,
    PromptDefinition,
    ValidationCode,
    select_active_prompt,
    validate_user_prompt,
)

logger = logging.getLogger("aurion.api.me_prompts")

router = APIRouter(prefix="/me", tags=["me"])

#: Sentinel session id for prompt-config audit events. These events
#: aren't bound to any particular session — they describe a per-
#: physician configuration change. The all-zeros UUID matches the
#: convention established by ``VISION_CLIP_PROBED`` (P1-FU-GEMINI-
#: PROBE).
_PROMPT_AUDIT_SESSION_ID: str = "00000000-0000-0000-0000-000000000000"


# Roles permitted to read the prompt catalog. CLINICIAN is the primary
# audience; ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER are included so
# support can answer "show me what the AI was told" without standing up
# a separate admin surface.
_READ_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.CLINICIAN,
        UserRole.ADMIN,
        UserRole.EVAL_TEAM,
        UserRole.COMPLIANCE_OFFICER,
    }
)


async def require_prompts_reader(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Allow CLINICIAN / ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER on the
    read path."""
    if user.role not in _READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"AI Prompts Transparency is readable by clinical + "
                f"admin / compliance / eval roles only (got "
                f"{user.role.value})"
            ),
        )
    return user


async def require_clinician(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Write paths (PATCH / DELETE) are CLINICIAN-only.

    User prompts are per-physician personal config. Admins must not
    edit them on a physician's behalf — that would defeat the whole
    "physician sees + signs off on the prompt the LLM receives"
    transparency story.
    """
    if user.role is not UserRole.CLINICIAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only clinicians can edit their own AI prompts (got "
                f"{user.role.value})"
            ),
        )
    return user


class PromptResponse(BaseModel):
    """Wire shape for one prompt card on the portal Transparency page.

    Mirrors :class:`PromptDefinition` for the read path. Phase B fields
    under replacement semantics:

      * ``system_prompt`` — the registry default. Used when the caller
        has not saved a user prompt; otherwise it's the editor's
        "what the default looks like" preview pane.
      * ``system_prompt_is_fallback`` — always ``True``. The portal
        renders the system prompt with muted styling to make clear
        it's the fallback, not the default that will run.
      * ``user_prompt_text`` — the calling physician's saved
        REPLACEMENT prompt, or ``None``.
      * ``is_overridden`` — convenience flag (``user_prompt_text is
        not None``). Drives the "Custom prompt active" badge.
      * ``active_prompt`` — the EXACT text that will be sent to the
        LLM on this physician's next call: ``user_prompt_text`` when
        set, ``system_prompt`` otherwise. Replaces v1's
        ``assembled_preview`` (which implied concatenation); the
        rename makes the selection semantics legible at the API
        boundary.
    """

    id: str
    name: str
    purpose: str
    category: str
    runs_when: str
    provider_field: str
    system_prompt: str
    system_prompt_is_fallback: bool = Field(
        default=True,
        description=(
            "Always True under replacement semantics — the system "
            "prompt is the fallback, used only when the caller has not "
            "saved a user_prompt_text."
        ),
    )
    schema_note: str | None
    user_prompt_text: str | None = Field(
        default=None,
        description=(
            "Per-physician REPLACEMENT prompt. None when the physician "
            "hasn't saved one (the system_prompt is used instead)."
        ),
    )
    is_overridden: bool = Field(
        default=False,
        description=(
            "True when user_prompt_text is set. Convenience flag for "
            "the UI badge."
        ),
    )
    active_prompt: str = Field(
        description=(
            "The exact prompt text the LLM would receive for this "
            "physician's next call: user_prompt_text when set, "
            "system_prompt otherwise. NOT concatenation."
        ),
    )


class PromptUserPromptUpdate(BaseModel):
    """PATCH request body — the full standalone user prompt."""

    user_prompt_text: str = Field(
        description=(
            "The physician's full standalone system prompt that will "
            "REPLACE the registry default for their own sessions. "
            "Validated structurally at save time (length cap + banlist "
            "+ required descriptive-mode anchors) — see "
            "app.modules.prompts.safety."
        ),
    )


def _serialize(
    prompt: PromptDefinition,
    user_prompt_text: Optional[str],
) -> PromptResponse:
    """Project a registry entry + the caller's user prompt (or None)
    onto the wire schema.

    Single point of projection logic. The list endpoint maps every
    registry entry through this; the PATCH / DELETE endpoints project
    the freshly-saved (or just-cleared) row through it too — so all
    three endpoints return byte-identical shapes.
    """
    return PromptResponse(
        id=prompt.id,
        name=prompt.name,
        purpose=prompt.purpose,
        category=prompt.category,
        runs_when=prompt.runs_when,
        provider_field=prompt.provider_field,
        system_prompt=prompt.system_prompt,
        system_prompt_is_fallback=True,
        schema_note=prompt.schema_note,
        user_prompt_text=user_prompt_text,
        is_overridden=user_prompt_text is not None,
        active_prompt=select_active_prompt(prompt.id, user_prompt_text),
    )


async def _get_owner_user_prompts(
    db: AsyncSession, owner_id: uuid.UUID
) -> dict[str, str]:
    """Fetch every user prompt this physician has saved, keyed by
    prompt_id. One DB round-trip, then project against the registry
    in memory — cheaper than N+1 lookups in the list endpoint."""
    stmt = select(PromptOverrideModel).where(
        PromptOverrideModel.owner_id == owner_id
    )
    result = await db.execute(stmt)
    return {row.prompt_id: row.user_prompt_text for row in result.scalars().all()}


# ── GET — list ──────────────────────────────────────────────────────────────


@router.get(
    "/prompts",
    response_model=list[PromptResponse],
    summary="List the AI system prompts the encounter pipeline uses",
)
async def list_my_prompts(
    user: CurrentUser = Depends(require_prompts_reader),
    db: AsyncSession = Depends(get_db),
) -> list[PromptResponse]:
    """Return the read-only catalog + per-physician user prompt for
    each entry.

    For CLINICIAN callers, the response includes their saved user
    prompts (when present). For ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER
    callers, the per-physician table doesn't apply to them (user
    prompts are per-clinician personal config) — they always see
    ``user_prompt_text=None`` and ``active_prompt == system_prompt``.
    This keeps the response strictly the caller's view: support roles
    never inspect another physician's prompts through this endpoint.
    """
    user_prompts_by_id: dict[str, str] = {}
    if user.role is UserRole.CLINICIAN:
        user_prompts_by_id = await _get_owner_user_prompts(db, user.user_id)
    return [
        _serialize(p, user_prompts_by_id.get(p.id)) for p in PROMPTS.values()
    ]


# ── PATCH — save / update user prompt ───────────────────────────────────────


def _prompt_or_404(prompt_id: str) -> PromptDefinition:
    """Look up a registry entry or return 404.

    Used by PATCH and DELETE to validate the path parameter against
    the in-code registry. Keeps the role-gate and validation layers
    free of DB lookups for an obviously-bad id.
    """
    if prompt_id not in PROMPTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown prompt_id: {prompt_id}",
        )
    return PROMPTS[prompt_id]


@router.patch(
    "/prompts/{prompt_id}",
    response_model=PromptResponse,
    summary="Save or update the calling physician's user prompt",
)
async def patch_my_user_prompt(
    prompt_id: str,
    body: PromptUserPromptUpdate,
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> PromptResponse:
    """Validate + upsert the calling physician's user prompt for
    ``prompt_id``.

    Returns the updated PromptResponse (same shape as the list
    endpoint) on success. On safety failure returns 400 with the
    matched_phrase (for banned-phrase failures) or
    missing_anchor_group (for the descriptive-mode anchor check)
    echoed back — the physician sees *exactly* what tripped the gate.
    """
    prompt = _prompt_or_404(prompt_id)

    # Structural safety gate. The matched_phrase echo is safe to
    # surface — it's the BANLIST entry, not patient content. The
    # missing_anchor_group is an index, also safe to surface.
    user_prompt_text = (
        body.user_prompt_text.strip() if body.user_prompt_text else ""
    )
    validation = validate_user_prompt(user_prompt_text)
    if validation.code is not ValidationCode.OK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": validation.message,
                "code": validation.code.value,
                "matched_phrase": validation.matched_phrase,
                "missing_anchor_group": validation.missing_anchor_group,
            },
        )

    # Upsert. We avoid the dialect-specific INSERT ... ON CONFLICT
    # because the SQLAlchemy 2.0 async path here is the same one the
    # rest of the codebase uses for tiny tables (PhysicianMacroModel
    # follows the same pattern in modules/macros/service.py).
    existing = await db.execute(
        select(PromptOverrideModel).where(
            PromptOverrideModel.owner_id == user.user_id,
            PromptOverrideModel.prompt_id == prompt_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = PromptOverrideModel(
            id=uuid.uuid4(),
            owner_id=user.user_id,
            prompt_id=prompt_id,
            user_prompt_text=user_prompt_text,
        )
        db.add(row)
    else:
        row.user_prompt_text = user_prompt_text
    await db.flush()

    # Audit — user_prompt_length only, NEVER the text. Personal
    # phrasing stays out of the immutable trail.
    await write_audit(
        _PROMPT_AUDIT_SESSION_ID,
        AuditEventType.PROMPT_USER_PROMPT_SET,
        actor_id=str(user.user_id),
        prompt_id=prompt_id,
        user_prompt_length=len(user_prompt_text),
    )
    await db.commit()

    logger.info(
        "User prompt saved: clinician=%s prompt=%s length=%d",
        user.user_id, prompt_id, len(user_prompt_text),
    )
    return _serialize(prompt, user_prompt_text)


# ── DELETE — remove user prompt (fall back to system default) ──────────────


@router.delete(
    "/prompts/{prompt_id}",
    response_model=PromptResponse,
    summary="Clear the calling physician's user prompt (use system default)",
)
async def delete_my_user_prompt(
    prompt_id: str,
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> PromptResponse:
    """Remove the saved user prompt so the registry default takes over.

    Idempotent: deleting a non-existent row is a no-op (still returns
    200 with the system-default PromptResponse) so the UI doesn't have
    to special-case "already at default".
    """
    prompt = _prompt_or_404(prompt_id)

    await db.execute(
        delete(PromptOverrideModel).where(
            PromptOverrideModel.owner_id == user.user_id,
            PromptOverrideModel.prompt_id == prompt_id,
        )
    )
    await write_audit(
        _PROMPT_AUDIT_SESSION_ID,
        AuditEventType.PROMPT_USER_PROMPT_CLEARED,
        actor_id=str(user.user_id),
        prompt_id=prompt_id,
    )
    await db.commit()

    logger.info(
        "User prompt cleared: clinician=%s prompt=%s",
        user.user_id, prompt_id,
    )
    return _serialize(prompt, None)
