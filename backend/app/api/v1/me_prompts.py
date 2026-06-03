"""Self-scoped AI Prompts Transparency endpoint.

Exposes the read-only catalog of LLM system prompts the encounter
analysis pipeline uses. Backs the ``/portal/prompts`` page in the web
portal so pilot physicians can audit how the AI is instructed.

Why not folded into ``app/api/v1/me.py``?
  * ``me.py`` is gated CLINICIAN-only at the router level (each /me/*
    endpoint depends on ``get_current_clinician`` which 403s every
    other role). This Transparency endpoint is intentionally readable
    by ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER too — those roles need
    visibility into the safety surface for support and audit. Mounting
    in its own file keeps the role-gate scope narrow + explicit.
  * Phase B will add per-physician overlay edits; those WILL be
    CLINICIAN-only (write paths). Keeping the read endpoint
    independently mounted gives Phase B a clean place to add a sibling
    write router without re-jiggering ``me.py``'s blanket gate.

Read-only metadata endpoint — no DB reads, no audit writes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.prompts import PROMPTS, PromptDefinition

logger = logging.getLogger("aurion.api.me_prompts")

router = APIRouter(prefix="/me", tags=["me"])


# Roles permitted to read the prompt catalog. CLINICIAN is the primary
# audience; ADMIN/EVAL_TEAM/COMPLIANCE_OFFICER are included so support
# can answer "show me what the AI was told" without standing up a
# separate admin surface. CLINICAL_ADMIN inherits the CLINICIAN scope
# semantically — it's an ops role, not a clinician identity, so it
# stays out of this gate.
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
    """Allow CLINICIAN / ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER.

    Single-purpose dependency — keeps ISP narrow (cf. AURION-CODING-
    WORKFLOW §6c). No DB reads, no audit emission.
    """
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


class PromptResponse(BaseModel):
    """Wire shape for one prompt card on the portal Transparency page.

    Mirrors :class:`PromptDefinition` for the read path and adds the
    forward-compatible overlay fields so Phase B doesn't need a
    schema migration:

      * ``override_text`` — the calling physician's customised
        instructions, if any. Always ``None`` in Phase A.
      * ``is_overridden`` — convenience flag. Always ``False`` in
        Phase A.

    Clients should render ``override_text`` when present and fall
    back to ``system_prompt`` otherwise.
    """

    id: str
    name: str
    purpose: str
    category: str
    runs_when: str
    provider_field: str
    system_prompt: str
    schema_note: str | None
    override_text: str | None = Field(
        default=None,
        description=(
            "Phase B: the calling physician's customised instructions. "
            "Always None in Phase A."
        ),
    )
    is_overridden: bool = Field(
        default=False,
        description=(
            "Phase B: True when override_text differs from "
            "system_prompt. Always False in Phase A."
        ),
    )


def _serialize(prompt: PromptDefinition) -> PromptResponse:
    """Project a registry definition onto the wire schema.

    Single point of override-overlay logic for Phase B: the only
    function that has to change to start emitting per-physician
    overrides is this one. Today it's a straight projection with
    static defaults.
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
        override_text=None,
        is_overridden=False,
    )


@router.get(
    "/prompts",
    response_model=list[PromptResponse],
    summary="List the AI system prompts the encounter pipeline uses",
)
async def list_my_prompts(
    _user: CurrentUser = Depends(require_prompts_reader),
) -> list[PromptResponse]:
    """Return the read-only catalog of LLM system prompts.

    The list is stable (insertion order of the registry dict) so the
    portal UI can preserve card order without sorting client-side.
    """
    return [_serialize(p) for p in PROMPTS.values()]
