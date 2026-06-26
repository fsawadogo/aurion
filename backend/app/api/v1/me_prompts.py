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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import raise_if_validation_failed, write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import PromptOverrideModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.appconfig_client import get_config
from app.modules.note_gen.few_shot import get_few_shot_examples
from app.modules.note_gen.service import (
    get_template,
    list_available_templates,
    specialty_style_prompt_id,
)
from app.modules.note_gen.specialty_style import get_specialty_style
from app.modules.prompts import (
    PROMPTS,
    PromptDefinition,
    select_active_prompt,
    validate_specialty_guidance,
    validate_user_prompt,
)
from app.modules.prompts.assembly import (
    PublishedPromptMeta,
    get_active_publications_for,
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


class AdminPublicationResponse(BaseModel):
    """An active admin-published Studio prompt applying to the caller's cohort
    for this job (``SELF`` / ``ROLE`` / ``ALL``), shown read-only on the
    Transparency page so a clinician can SEE the prompt an admin shared.

    Present whenever such a publication exists — even when the caller has their
    own override (``is_overridden`` True), in which case the override still wins
    at runtime and the UI flags this as shadowed. Display metadata only; never
    the prompt text.
    """

    name: str
    version_no: int
    scope: str = Field(description="Publication cohort: SELF | ROLE | ALL.")
    target_role: str | None = Field(
        default=None,
        description="Role the prompt was published to, when scope == ROLE.",
    )
    published_at: datetime


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
    admin_publication: AdminPublicationResponse | None = Field(
        default=None,
        description=(
            "Active admin-published Studio prompt applying to the caller for "
            "this job, or None. Drives the read-only 'published by your admin' "
            "banner. When is_overridden is also True, the publication is "
            "shadowed by the caller's personal prompt at runtime."
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


def _publication_response(
    meta: Optional[PublishedPromptMeta],
) -> Optional[AdminPublicationResponse]:
    """Project the assembly-layer publication metadata onto the wire model
    (or None when no admin publication applies to the caller for this job)."""
    if meta is None:
        return None
    return AdminPublicationResponse(
        name=meta.name,
        version_no=meta.version_no,
        scope=meta.scope,
        target_role=meta.target_role,
        published_at=meta.published_at,
    )


def _serialize(
    prompt: PromptDefinition,
    user_prompt_text: Optional[str],
    publication: Optional[AdminPublicationResponse] = None,
) -> PromptResponse:
    """Project a registry entry + the caller's user prompt (or None) + the
    active admin publication (or None) onto the wire schema.

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
        admin_publication=publication,
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
    publications = await get_active_publications_for(
        db, user.user_id, list(PROMPTS.keys())
    )
    return [
        _serialize(
            p,
            user_prompts_by_id.get(p.id),
            _publication_response(publications.get(p.id)),
        )
        for p in PROMPTS.values()
    ]


# ── GET — per-specialty prompt layer (transparency) ─────────────────────────


class SpecialtySectionResponse(BaseModel):
    id: str
    title: str
    required: bool
    description: str
    visual_trigger_keywords: list[str]


class SpecialtyExampleResponse(BaseModel):
    description: str
    populated_sections: list[str]


class SpecialtyPromptResponse(BaseModel):
    """The specialty-specific layer injected into the Stage 1 note prompt on
    top of the (global) note-generation system prompt: the style guidance, the
    template sections + their visual-trigger keywords, and a summary of the
    worked few-shot examples.

    The STYLE guidance is per-physician overridable (replacement semantics for
    the guidance text only — the immutable base system prompt below it always
    carries the descriptive-mode boundary). Override fields mirror the global
    registry-prompt shape:

      * ``guidance`` — the shipped DEFAULT style snippet (kept under this name
        for backward-compat; treat it as the "default" preview).
      * ``user_guidance`` — the calling physician's saved override, or None.
      * ``is_overridden`` — convenience flag (``user_guidance is not None``).
      * ``active_guidance`` — what the live prompt would actually use:
        ``user_guidance`` when set, else ``guidance``.
      * ``enabled`` — whether the specialty-style layer is currently wired
        into live note generation
        (``feature_flags.specialty_style_in_prompt_enabled``). When False the
        guidance (default or override) is NOT sent to the model — the UI uses
        this to warn that edits are saved but dormant.
    """

    key: str
    display_name: str
    guidance: str
    user_guidance: str | None = None
    is_overridden: bool = False
    active_guidance: str
    enabled: bool
    sections: list[SpecialtySectionResponse]
    examples: list[SpecialtyExampleResponse]
    examples_count: int


def _serialize_specialty(
    key: str, user_guidance: Optional[str], enabled: bool
) -> SpecialtyPromptResponse:
    """Project a specialty's template + style + examples + the caller's saved
    guidance override onto the wire schema. Single point of projection so GET
    and PATCH/DELETE return byte-identical shapes."""
    template = get_template(key)
    examples = get_few_shot_examples(key)
    default_guidance = get_specialty_style(key)
    return SpecialtyPromptResponse(
        key=template.key,
        display_name=template.display_name,
        guidance=default_guidance,
        user_guidance=user_guidance,
        is_overridden=user_guidance is not None,
        active_guidance=user_guidance if user_guidance is not None else default_guidance,
        enabled=enabled,
        sections=[
            SpecialtySectionResponse(
                id=s.id,
                title=s.title,
                required=s.required,
                description=getattr(s, "description", "") or "",
                visual_trigger_keywords=getattr(
                    s, "visual_trigger_keywords", []
                )
                or [],
            )
            for s in template.sections
        ],
        examples=[
            SpecialtyExampleResponse(
                description=ex.get("description", ""),
                populated_sections=[
                    s.get("id", "")
                    for s in ex.get("note", {}).get("sections", [])
                    if s.get("status") == "populated"
                ],
            )
            for ex in examples
        ],
        examples_count=len(examples),
    )


async def _get_owner_specialty_guidance(
    db: AsyncSession, owner_id: uuid.UUID
) -> dict[str, str]:
    """Fetch every specialty STYLE override this physician has saved, keyed by
    specialty key (the ``specialty_style:`` prefix stripped). One round-trip,
    projected against the template list in memory — same shape as
    ``_get_owner_user_prompts`` for the registry prompts."""
    stmt = select(PromptOverrideModel).where(
        PromptOverrideModel.owner_id == owner_id,
        PromptOverrideModel.prompt_id.like(f"{_SPECIALTY_PREFIX}%"),
    )
    result = await db.execute(stmt)
    return {
        row.prompt_id[len(_SPECIALTY_PREFIX):]: row.user_prompt_text
        for row in result.scalars().all()
    }


#: Mirror of ``note_gen.service.SPECIALTY_STYLE_PROMPT_PREFIX`` for the
#: ``prompt_id`` namespace, via the public ``specialty_style_prompt_id``.
_SPECIALTY_PREFIX: str = specialty_style_prompt_id("")


def _specialty_or_404(key: str) -> None:
    """Validate the specialty key against the in-code template list or 404."""
    if key not in set(list_available_templates()):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown specialty: {key}",
        )


@router.get(
    "/prompts/specialties",
    response_model=list[SpecialtyPromptResponse],
    summary="Per-specialty note-generation guidance, sections, and example summaries",
)
async def list_specialty_prompts(
    user: CurrentUser = Depends(require_prompts_reader),
    db: AsyncSession = Depends(get_db),
) -> list[SpecialtyPromptResponse]:
    """List the specialty layer + the caller's saved guidance overrides.

    For CLINICIAN callers the response carries their saved guidance
    (``user_guidance`` / ``is_overridden`` / ``active_guidance``). Support
    roles (ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER) never inspect another
    physician's overrides through this endpoint — they always see
    ``user_guidance=None``. ``enabled`` reflects the live feature flag for
    everyone."""
    enabled = get_config().feature_flags.specialty_style_in_prompt_enabled
    guidance_by_key: dict[str, str] = {}
    if user.role is UserRole.CLINICIAN:
        guidance_by_key = await _get_owner_specialty_guidance(db, user.user_id)
    return [
        _serialize_specialty(key, guidance_by_key.get(key), enabled)
        for key in sorted(list_available_templates())
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
    raise_if_validation_failed(validation)

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
    publications = await get_active_publications_for(db, user.user_id, [prompt_id])
    return _serialize(
        prompt, user_prompt_text, _publication_response(publications.get(prompt_id))
    )


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
    publications = await get_active_publications_for(db, user.user_id, [prompt_id])
    return _serialize(
        prompt, None, _publication_response(publications.get(prompt_id))
    )


# ── PATCH / DELETE — per-physician specialty STYLE guidance override ─────────


class SpecialtyGuidanceUpdate(BaseModel):
    """PATCH body — the physician's replacement STYLE guidance for a specialty.

    Validated by ``validate_specialty_guidance`` (length + injection/role-flip
    banlist). The descriptive-mode anchor requirement does NOT apply here: this
    text is ADDITIVE to the always-present base note system prompt, which keeps
    the descriptive-mode boundary — unlike the registry-prompt override, which
    replaces the system prompt and so must self-contain it."""

    guidance: str = Field(
        description=(
            "The physician's specialty STYLE guidance that replaces the "
            "shipped default for their own sessions. Additive on top of the "
            "base note system prompt; validated structurally at save time."
        ),
    )


@router.patch(
    "/prompts/specialties/{key}",
    response_model=SpecialtyPromptResponse,
    summary="Save or update the calling physician's specialty STYLE guidance",
)
async def patch_my_specialty_guidance(
    key: str,
    body: SpecialtyGuidanceUpdate,
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> SpecialtyPromptResponse:
    """Validate + upsert the calling physician's STYLE guidance override for
    ``key``. 404 for an unknown specialty; 400 (with ``matched_phrase``) on a
    banlist hit. Stored in the shared ``prompt_overrides`` table under the
    ``specialty_style:`` namespace so it reuses the registry-override machinery
    without a new table."""
    _specialty_or_404(key)

    guidance = body.guidance.strip() if body.guidance else ""
    validation = validate_specialty_guidance(guidance)
    raise_if_validation_failed(validation)

    prompt_id = specialty_style_prompt_id(key)
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
            user_prompt_text=guidance,
        )
        db.add(row)
    else:
        row.user_prompt_text = guidance
    await db.flush()

    # Audit — length only, never the text. The namespaced prompt_id
    # distinguishes a specialty-guidance change from a registry-prompt change
    # in the trail.
    await write_audit(
        _PROMPT_AUDIT_SESSION_ID,
        AuditEventType.PROMPT_USER_PROMPT_SET,
        actor_id=str(user.user_id),
        prompt_id=prompt_id,
        user_prompt_length=len(guidance),
    )
    await db.commit()

    logger.info(
        "Specialty guidance saved: clinician=%s specialty=%s length=%d",
        user.user_id, key, len(guidance),
    )
    enabled = get_config().feature_flags.specialty_style_in_prompt_enabled
    return _serialize_specialty(key, guidance, enabled)


@router.delete(
    "/prompts/specialties/{key}",
    response_model=SpecialtyPromptResponse,
    summary="Clear the calling physician's specialty STYLE guidance (use default)",
)
async def delete_my_specialty_guidance(
    key: str,
    user: CurrentUser = Depends(require_clinician),
    db: AsyncSession = Depends(get_db),
) -> SpecialtyPromptResponse:
    """Remove the saved guidance override so the shipped default takes over.
    Idempotent — clearing a non-existent override returns 200 with the default
    projection."""
    _specialty_or_404(key)

    prompt_id = specialty_style_prompt_id(key)
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
        "Specialty guidance cleared: clinician=%s specialty=%s",
        user.user_id, key,
    )
    enabled = get_config().feature_flags.specialty_style_in_prompt_enabled
    return _serialize_specialty(key, None, enabled)
