"""Self-scoped AI Prompts Transparency endpoints.

Phase A (read-only) and Phase B (per-physician append-only overlays).

The GET path lists every LLM system prompt the encounter pipeline uses
plus the calling physician's current overlay (or ``None``) and an
``assembled_preview`` of the combined text that would be sent to the
LLM today. PATCH lets the physician save / update an overlay; DELETE
resets to the base prompt.

Why a separate router (not folded into ``me.py``)?
  * ``me.py`` is gated CLINICIAN-only at the router level. The GET path
    here is intentionally readable by ADMIN / EVAL_TEAM /
    COMPLIANCE_OFFICER too — support roles need visibility into the
    safety surface.
  * The PATCH / DELETE paths ARE CLINICIAN-only (no physician proxy on
    their behalf). Mounting them in this same file keeps the prompt
    feature contained in one place; the role gating is per-endpoint
    via the dependency in `Depends(...)`.

Audit invariants
----------------
- Every PATCH writes ``PROMPT_OVERRIDE_SET`` with kwargs
  ``{actor_id, prompt_id, overlay_length}`` — never the overlay text.
- Every DELETE writes ``PROMPT_OVERRIDE_CLEARED`` with
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
    assemble_preview,
    validate_overlay,
)

logger = logging.getLogger("aurion.api.me_prompts")

router = APIRouter(prefix="/me", tags=["me"])

#: Sentinel session id for overlay audit events. These events aren't
#: bound to any particular session — they describe a per-physician
#: configuration change. The all-zeros UUID matches the convention
#: established by ``VISION_CLIP_PROBED`` (P1-FU-GEMINI-PROBE).
_OVERLAY_AUDIT_SESSION_ID: str = "00000000-0000-0000-0000-000000000000"


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

    Overlays are per-physician personal preferences. Admins must not
    edit them on a physician's behalf — that would defeat the whole
    "physician sees + signs off on the prompt the LLM receives"
    transparency story.
    """
    if user.role is not UserRole.CLINICIAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only clinicians can edit their own prompt overlays "
                f"(got {user.role.value})"
            ),
        )
    return user


class PromptResponse(BaseModel):
    """Wire shape for one prompt card on the portal Transparency page.

    Mirrors :class:`PromptDefinition` for the read path and adds the
    Phase B per-physician overlay fields:

      * ``overlay_text`` — the calling physician's customised
        instructions, or ``None`` when they haven't set one.
      * ``is_overridden`` — convenience flag (``overlay_text is not
        None``).
      * ``assembled_preview`` — the combined text the LLM would
        actually receive today (``base + separator + overlay`` when
        overridden; just ``base`` otherwise). Pre-computed so the
        client doesn't re-assemble on every render.
    """

    id: str
    name: str
    purpose: str
    category: str
    runs_when: str
    provider_field: str
    system_prompt: str
    schema_note: str | None
    overlay_text: str | None = Field(
        default=None,
        description=(
            "Per-physician append-only customisation. None when the "
            "physician hasn't set an overlay."
        ),
    )
    is_overridden: bool = Field(
        default=False,
        description=(
            "True when overlay_text is set. Convenience flag for the UI."
        ),
    )
    assembled_preview: str = Field(
        description=(
            "The combined prompt text (base + overlay) the LLM would "
            "receive today. Equal to system_prompt when no overlay set."
        ),
    )


class PromptOverrideUpdate(BaseModel):
    """PATCH request body."""

    overlay_text: str = Field(
        description=(
            "The physician's overlay text to append below the base "
            "prompt. Validated structurally at save time (length cap + "
            "banlist) — see app.modules.prompts.safety."
        ),
    )


def _serialize(
    prompt: PromptDefinition,
    overlay_text: Optional[str],
) -> PromptResponse:
    """Project a registry entry + the caller's overlay (or None) onto
    the wire schema.

    Single point of overlay-projection logic. The list endpoint maps
    every registry entry through this; the PATCH / DELETE endpoints
    project the freshly-saved (or just-cleared) row through it too —
    so all three endpoints return byte-identical shapes.
    """
    return PromptResponse(
        id=prompt.id,
        name=prompt.name,
        purpose=prompt.purpose,
        category=prompt.category,
        runs_when=prompt.runs_when,
        provider_field=prompt.provider_field,
        system_prompt=prompt.system_prompt,
        schema_note=prompt.schema_note,
        overlay_text=overlay_text,
        is_overridden=overlay_text is not None,
        assembled_preview=assemble_preview(prompt.id, overlay_text),
    )


async def _get_owner_overlays(
    db: AsyncSession, owner_id: uuid.UUID
) -> dict[str, str]:
    """Fetch every overlay this physician has saved, keyed by
    prompt_id. One DB round-trip, then we project against the registry
    in memory — cheaper than N+1 lookups in the list endpoint."""
    stmt = select(PromptOverrideModel).where(
        PromptOverrideModel.owner_id == owner_id
    )
    result = await db.execute(stmt)
    return {row.prompt_id: row.overlay_text for row in result.scalars().all()}


async def _get_single_overlay(
    db: AsyncSession, owner_id: uuid.UUID, prompt_id: str
) -> Optional[str]:
    """Fetch a single overlay row's text (or None)."""
    stmt = select(PromptOverrideModel.overlay_text).where(
        PromptOverrideModel.owner_id == owner_id,
        PromptOverrideModel.prompt_id == prompt_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


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
    """Return the read-only catalog + per-physician overlay overlay.

    For CLINICIAN callers, the response includes their saved overlays
    (when present). For ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER callers,
    the per-physician overlay table doesn't apply to them (overlays
    are per-clinician personal config) — they always see
    ``overlay_text=None`` / base-only assembled_preview. This keeps the
    response strictly the caller's view: support roles never inspect
    another physician's preferences through this endpoint.
    """
    overlays_by_prompt: dict[str, str] = {}
    if user.role is UserRole.CLINICIAN:
        overlays_by_prompt = await _get_owner_overlays(db, user.user_id)
    return [
        _serialize(p, overlays_by_prompt.get(p.id)) for p in PROMPTS.values()
    ]


# ── PATCH — save / update overlay ───────────────────────────────────────────


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
    summary="Save or update the calling physician's overlay on a prompt",
)
async def patch_my_prompt_override(
    prompt_id: str,
    body: PromptOverrideUpdate,
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> PromptResponse:
    """Validate + upsert the calling physician's overlay on
    ``prompt_id``.

    Returns the updated PromptResponse (same shape as the list
    endpoint) on success. On safety failure returns 400 with the
    matched_phrase echoed back when applicable — the physician sees
    *exactly* which phrase tripped the gate.
    """
    prompt = _prompt_or_404(prompt_id)

    # Structural safety gate. The matched_phrase echo is safe to
    # surface — it's the BANLIST entry, not patient content.
    overlay_text = body.overlay_text.strip() if body.overlay_text else ""
    validation = validate_overlay(overlay_text)
    if validation.code is not ValidationCode.OK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": validation.message,
                "code": validation.code.value,
                "matched_phrase": validation.matched_phrase,
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
            overlay_text=overlay_text,
        )
        db.add(row)
    else:
        row.overlay_text = overlay_text
    await db.flush()

    # Audit — overlay_length only, NEVER the overlay text. Personal
    # phrasing stays out of the immutable trail.
    await write_audit(
        _OVERLAY_AUDIT_SESSION_ID,
        AuditEventType.PROMPT_OVERRIDE_SET,
        actor_id=str(user.user_id),
        prompt_id=prompt_id,
        overlay_length=len(overlay_text),
    )
    await db.commit()

    logger.info(
        "Prompt overlay saved: clinician=%s prompt=%s length=%d",
        user.user_id, prompt_id, len(overlay_text),
    )
    return _serialize(prompt, overlay_text)


# ── DELETE — reset to base ──────────────────────────────────────────────────


@router.delete(
    "/prompts/{prompt_id}",
    response_model=PromptResponse,
    summary="Clear the calling physician's overlay (reset to base)",
)
async def delete_my_prompt_override(
    prompt_id: str,
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> PromptResponse:
    """Reset to the base prompt by deleting the overlay row.

    Idempotent: deleting a non-existent overlay is a no-op (still
    returns 200 with the base-only PromptResponse) so the UI doesn't
    have to special-case "already at base".
    """
    prompt = _prompt_or_404(prompt_id)

    await db.execute(
        delete(PromptOverrideModel).where(
            PromptOverrideModel.owner_id == user.user_id,
            PromptOverrideModel.prompt_id == prompt_id,
        )
    )
    await write_audit(
        _OVERLAY_AUDIT_SESSION_ID,
        AuditEventType.PROMPT_OVERRIDE_CLEARED,
        actor_id=str(user.user_id),
        prompt_id=prompt_id,
    )
    await db.commit()

    logger.info(
        "Prompt overlay cleared: clinician=%s prompt=%s",
        user.user_id, prompt_id,
    )
    return _serialize(prompt, None)
