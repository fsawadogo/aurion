"""Profile API routes — physician preferences and practice configuration.

Endpoints are accessible to any authenticated user for their own profile.
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.text_validation import validate_user_text
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.custom_templates import service as custom_templates_service
from app.modules.note_gen.service import list_available_templates
from app.modules.profile.service import (
    get_or_create_profile,
    get_preferred_template_objects,
    update_profile,
)

router = APIRouter(prefix="/profile", tags=["profile"])

# Profile-scoped events aren't tied to a clinical session. Same synthetic
# anchor that the auth / MFA / prompt-overlay paths use so the row stays
# out of any real session's history while remaining queryable on
# (event_type, actor_id).
_PROFILE_AUDIT_SESSION = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Canonical default consultation-type keys. Anything not in this set on
# the consultation_types list is treated as a clinician-authored custom
# label. Kept here (not imported from another module) because the iOS and
# portal clients also hard-code this list — duplicating the four keys is
# cheaper than adding a separate config table for what will always be a
# short, stable set of defaults.
_DEFAULT_CONSULTATION_TYPES = frozenset(
    {"new_patient", "follow_up", "pre_op", "post_op"}
)

# Hard caps enforced server-side. Mirrors the iOS-side / portal-side
# limits so a client that bypasses its own gates still can't write
# pathological data. 20 customs is a soft pilot limit (Dr. Marie at #259
# expects single-digit counts); the 60-char cap is generous enough to
# carry "Lower-Limb New Patient" while bounding the audit risk.
_MAX_CUSTOM_CONSULTATION_TYPES = 20
_MAX_CONSULTATION_TYPE_LEN = 60

# Per-visit-type soft cap on contexts (#313, B1). Mirrors the
# consultation-type cap rationale — a generous bound that a runaway
# client can't blow past while staying well above realistic pilot use
# (Dr. Marie / Dr. Perry expect a handful per visit type).
_MAX_CONTEXTS_PER_VISIT_TYPE = 30

# Free-text context description cap (Marie pilot follow-up to #313). A
# context label is a short shorthand ("LL fu"); the description is the
# fuller note the physician wants the AI to "understand the context as
# fully as possible" — so it's a generous prose budget, not a label
# budget. 500 chars carries a few sentences while bounding audit risk.
_MAX_CONTEXT_DESCRIPTION_LEN = 500

# Context id shape: ``ctx_`` + 8 lowercase-hex chars, minted via
# ``secrets.token_hex(4)``. We preserve a client-supplied id ONLY when it
# matches this shape (i.e. a value round-tripped from a prior GET); any
# other value is regenerated so a client can't smuggle free text (PHI)
# into the id field.
_CONTEXT_ID_RE = re.compile(r"^ctx_[0-9a-f]{8}$")


def _assign_context_id(existing: Optional[str]) -> str:
    """Return a stable context id.

    Preserves a well-formed existing id (the edit path round-trips the
    id from a prior GET); mints a fresh ``ctx_<8 hex>`` id when absent,
    blank, or malformed.
    """
    if existing and _CONTEXT_ID_RE.match(existing.strip()):
        return existing.strip()
    return "ctx_" + secrets.token_hex(4)


def _validate_consultation_type(
    value: str, *, check_proper_noun: bool = False
) -> str:
    """Validate one custom consultation-type label.

    Returns the stripped value. Raises ``ValueError`` on any gate
    failure. Mirrors the iOS-side helper + the web-side
    ``validateConsultationType``. NEVER includes the rejected value in
    the error.

    Posture: SSN / email / 60-char cap gates are always on. The full-name
    gate is OFF — the clinician must be able to name a visit type or
    context with full descriptive words ("Limb Lengthening Cosmetic",
    "Breast Reconstruction") so the AI gets the context "as full as
    possible". The SSN / email / length gates still reject an actual
    identifier.

    ``check_proper_noun`` (default False as of the pilot "don't restrict"
    feedback) gates the residual "two capitalized word tokens" pattern
    (e.g. "Jane Doe"). It is OFF for both visit-type AND context labels —
    a Title-Case clinical phrase is legitimate shorthand, not a patient
    identifier, and rejecting it was friction with no PHI upside. The
    parameter is retained so a future caller can re-enable the heuristic
    for a genuinely per-patient field without reworking the gate.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("consultation type is empty")
    try:
        validate_user_text(
            stripped,
            max_length=_MAX_CONSULTATION_TYPE_LEN,
            reject_full_name=False,
        )
    except ValueError as exc:
        # Same shape as `_check_identifier_format` — surface the noun
        # the caller's catalog expects without re-implementing the
        # underlying gates.
        msg = str(exc).replace("text", "consultation type", 1)
        raise ValueError(msg) from None
    if check_proper_noun and _looks_like_proper_noun_pair(stripped):
        raise ValueError("consultation type looks like a full name")
    return stripped


def _looks_like_proper_noun_pair(value: str) -> bool:
    """Cheap "two-capitalized-words" heuristic.

    Catches the obvious "Jane Doe" / "Marie Gdalevitch" shape while
    leaving the typical clinician shorthand alone:
      * "LL fu"      → second token starts lowercase → OK
      * "Breast visit" → second token starts lowercase → OK
      * "Pre-op"     → single token → OK
      * "Jane Doe"   → both tokens start capital, all alpha → REJECT
      * "Marie M Gdalevitch" → all three tokens start capital → REJECT
    """
    tokens = [t for t in value.split() if t]
    if len(tokens) < 2:
        return False
    for tok in tokens:
        first = tok[0]
        # Each token must start with an uppercase letter and be entirely
        # alphabetic (letters + apostrophes / hyphens permitted) for the
        # pattern to trip. Anything with a digit or other punctuation
        # is treated as a clinician shorthand.
        if not first.isupper():
            return False
        if not all(c.isalpha() or c in {"'", "-", "’"} for c in tok):
            return False
    return True


def _split_defaults_customs(types: list[str]) -> tuple[set[str], set[str]]:
    """Partition a consultation-types list into (defaults, customs)."""
    defaults = {t for t in types if t in _DEFAULT_CONSULTATION_TYPES}
    customs = {t for t in types if t not in _DEFAULT_CONSULTATION_TYPES}
    return defaults, customs


# ── Schemas ─────────────────────────────────────────────────────────────────


class VisitTypeContext(BaseModel):
    """One context row under a visit type (#313, B1).

    A "context" is a clinician-authored sub-mode of a visit type — e.g.
    under "new_patient", contexts "LL" (lower limb) and "Breast" — each
    optionally pinned to a built-in specialty template.

    Validation posture mirrors custom consultation-type labels:
      * ``label`` goes through ``_validate_consultation_type`` (the shared
        ``validate_user_text`` format gate + proper-noun-pair heuristic).
      * ``id`` is server-assigned (``ctx_<8 hex>``) when absent/blank/
        malformed; a well-formed id is preserved on edit.
      * ``template_key``, when non-null, MUST reference a built-in
        template (``list_available_templates()``); else rejected.
      * ``template_ref`` (the custom-template pointer, #318 / B3) is the
        UUID of a ``custom_templates`` row the calling clinician owns. It
        is MUTUALLY EXCLUSIVE with ``template_key`` — a context binds
        either a built-in key OR a custom ref, never both. The
        ownership + existence check needs the DB and the caller's id, so
        it runs at PUT time in ``update_profile_route``; this model
        validator only enforces the cross-field mutual-exclusion rule
        and normalizes the stored value.

    ``hide_input_in_errors=True`` keeps a rejected label / ref out of any
    422 body / Sentry frame, same posture as ``UpdateProfileRequest``.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    id: str = ""
    label: str
    template_key: Optional[str] = None
    template_ref: Optional[str] = None
    # Optional free-text note (Marie pilot follow-up to #313). Travels to
    # the note-generation prompt as additional encounter context so the AI
    # can "understand the context as fully as possible". Prose, not a
    # label — validated WITHOUT the full-name / proper-noun heuristics.
    description: Optional[str] = None
    # Per-visit-type default (#577). At most one context per visit type may
    # set this; when a session is created with this visit type but NO chosen
    # context, the default's template is resolved instead of the specialty
    # default. The "<=1 per visit type" rule needs the sibling list in view,
    # so it is enforced in `_validate_contexts_per_visit_type`, not here.
    is_default: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "VisitTypeContext":
        # Label: same format gate as a custom consultation-type label, but
        # with the proper-noun heuristic OFF — a context is a reusable
        # clinical sub-mode ("Limb Length Discrepancy"), not a per-patient
        # field, so a legitimate Title-Case clinical phrase must pass. The
        # SSN / email / length gates still reject an actual identifier.
        # Raises ValueError (→ 422) without echoing the value.
        self.label = _validate_consultation_type(
            self.label, check_proper_noun=False
        )
        # Description: prose free-text. Blank → None so an empty string from
        # a client doesn't read as "a note is set". Validated through the
        # shared format gate (SSN / email / 500-char cap) with the full-name
        # heuristic OFF — a clinical note may legitimately read like prose
        # with capitalized terms. Never echoes the value into the 422.
        if self.description is not None:
            stripped_desc = self.description.strip()
            if not stripped_desc:
                self.description = None
            else:
                try:
                    validate_user_text(
                        stripped_desc,
                        max_length=_MAX_CONTEXT_DESCRIPTION_LEN,
                        reject_full_name=False,
                    )
                except ValueError as exc:
                    msg = str(exc).replace("text", "context description", 1)
                    raise ValueError(msg) from None
                self.description = stripped_desc
        # Id: preserve a well-formed round-tripped id, else server-assign.
        self.id = _assign_context_id(self.id)
        # Normalize the custom-template pointer: blank → None so an empty
        # string from a client doesn't read as "a ref is set".
        if self.template_ref is not None:
            self.template_ref = self.template_ref.strip() or None
        # Mutual exclusion (#318 / B3): a context binds EITHER a built-in
        # template_key OR a custom template_ref — never both. We reject
        # rather than silently dropping one so a confused client can't
        # half-apply its intent. ``hide_input_in_errors`` keeps the values
        # out of the 422 body.
        if self.template_key is not None and self.template_ref is not None:
            raise ValueError(
                "template_key and template_ref are mutually exclusive"
            )
        # template_key, when set, must be a built-in template key.
        if self.template_key is not None:
            if self.template_key not in list_available_templates():
                raise ValueError("template_key is not an available template")
        # NOTE: template_ref ownership + existence is validated at PUT time
        # (needs the DB + caller id) — see ``update_profile_route``. A
        # non-owned / nonexistent / malformed ref is REJECTED there (422),
        # never silently dropped.
        return self


class ProfileResponse(BaseModel):
    clinician_id: str
    display_name: str
    practice_type: Optional[str] = None
    primary_specialty: str
    preferred_templates: list[str]
    consultation_types: list[str]
    # Visit-type → context → template map (#313, B1). Returned as raw
    # stored dicts (not re-validated through ``VisitTypeContext``) so a
    # built-in template later removed from disk can't make a GET 500.
    contexts_per_visit_type: dict[str, list[dict]] = {}
    # Allied-health roster (#275). Raw stored dicts ({name, role, ...})
    # plus an injected ``present_today_effective`` bool computed on READ
    # from the stored ``present_today`` / ``present_today_date`` keys —
    # the day-roster auto-reset (stale date ⇒ absent). The iOS picker
    # filters on ``present_today_effective``. No PHI in any presence field.
    allied_health_team: list[dict] = []
    output_language: str
    # Portal/iOS chrome preferences (Phase A1). Distinct from
    # `output_language`: a physician may dictate in English and read
    # the chrome in French. `ui_theme` is "system" / "light" / "dark".
    ui_theme: str = "system"
    accent_color: str = "gold"
    ui_language: str = "en"
    auto_upload: bool = True
    retention_days: int = 7
    consent_reprompt: str = "every_session"

    model_config = {"from_attributes": True}


# #418/OV-7 curated accent palette — values map to pre-validated AA-contrast
# tokens in the frontend; not free-form hex (compliance surfaces stay fixed).
_ACCENT_PALETTE = {"gold", "teal", "indigo", "rose", "slate"}


class UpdateProfileRequest(BaseModel):
    # `hide_input_in_errors=True` is load-bearing here for
    # `consultation_types`: a clinician's custom label could in the worst
    # case carry a name even after the format gates, and Pydantic's
    # default `ValidationError` echoes the rejected `input_value`. We
    # want zero chance of that landing in 422 bodies or Sentry. Same
    # posture `ExternalReferenceIdRequest` in sessions.py takes.
    model_config = ConfigDict(hide_input_in_errors=True)

    display_name: Optional[str] = None
    practice_type: Optional[str] = None
    primary_specialty: Optional[str] = None
    preferred_templates: Optional[list[str]] = None
    consultation_types: Optional[list[str]] = None
    # Declared AFTER ``consultation_types`` on purpose: the validator below
    # reads the already-validated ``consultation_types`` off ``info.data``
    # to know which custom visit-type keys are canonical for THIS request.
    contexts_per_visit_type: Optional[dict[str, list[VisitTypeContext]]] = None
    allied_health_team: Optional[list[dict]] = None
    output_language: Optional[str] = None
    ui_theme: Optional[str] = None
    accent_color: Optional[str] = None
    ui_language: Optional[str] = None
    auto_upload: Optional[bool] = None
    retention_days: Optional[int] = None
    consent_reprompt: Optional[str] = None

    @field_validator("ui_theme")
    @classmethod
    def _validate_ui_theme(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in {"system", "light", "dark"}:
            raise ValueError("ui_theme must be one of: system, light, dark")
        return v

    @field_validator("accent_color")
    @classmethod
    def _validate_accent_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _ACCENT_PALETTE:
            raise ValueError(
                "accent_color must be one of: " + ", ".join(sorted(_ACCENT_PALETTE))
            )
        return v

    @field_validator("ui_language")
    @classmethod
    def _validate_ui_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Locked to en/fr today; widen here when iOS/portal locales grow.
        # The column itself holds up to 16 chars so IETF tags like
        # "fr-CA" forward-compat without a migration.
        if v not in {"en", "fr"}:
            raise ValueError("ui_language must be one of: en, fr")
        return v

    @field_validator("consultation_types")
    @classmethod
    def _validate_consultation_types(
        cls, v: Optional[list[str]]
    ) -> Optional[list[str]]:
        """Allow the 4 default keys as-is; gate every custom label.

        Custom labels (anything not in `_DEFAULT_CONSULTATION_TYPES`)
        go through `_validate_consultation_type`. The stripped /
        canonical form is what we persist — leading/trailing whitespace
        on input is forgiven so a clinician's "Breast visit " round-
        trips as "Breast visit".

        The 20-custom soft cap is enforced here so the API rejects
        before any audit row is written.
        """
        if v is None:
            return v
        cleaned: list[str] = []
        seen: set[str] = set()
        custom_count = 0
        for item in v:
            if not isinstance(item, str):
                raise ValueError("consultation type must be a string")
            if item in _DEFAULT_CONSULTATION_TYPES:
                # Defaults round-trip as the exact canonical key.
                canonical = item
            else:
                canonical = _validate_consultation_type(item)
                custom_count += 1
                if custom_count > _MAX_CUSTOM_CONSULTATION_TYPES:
                    raise ValueError(
                        f"max {_MAX_CUSTOM_CONSULTATION_TYPES} custom "
                        "consultation types"
                    )
            # De-dup case-sensitively. Two customs that differ only in
            # case ("LL fu" vs "ll fu") are treated as distinct by
            # design — physicians can choose their own casing.
            if canonical in seen:
                continue
            seen.add(canonical)
            cleaned.append(canonical)
        return cleaned

    @field_validator("contexts_per_visit_type")
    @classmethod
    def _validate_contexts_per_visit_type(
        cls,
        v: Optional[dict[str, list[VisitTypeContext]]],
        info: ValidationInfo,
    ) -> Optional[dict[str, list[VisitTypeContext]]]:
        """Gate the visit-type → context map (cross-field rules).

        Each context's label, id, ``template_key`` membership, and
        ``template_ref`` nulling are enforced by ``VisitTypeContext``
        itself (its model-validator runs first, during parsing). This
        validator adds the rules that need the whole request in view:

          * Every map KEY must be a canonical visit type — a built-in
            default ("new_patient", "follow_up", "pre_op", "post_op") OR a
            custom label present in the SAME request's
            ``consultation_types``. Orphan keys (a visit type the clinician
            removed or renamed) are PRUNED, not rejected, so a stale client
            map self-heals on the next write.
          * Per-visit-type soft cap of 30 contexts.
          * At most one context per visit type flagged ``is_default`` (#577).
        """
        if v is None:
            return v
        # Canonical key set = built-in defaults + this request's custom
        # consultation types. If the request omits ``consultation_types``
        # we fall back to defaults-only (custom-keyed contexts then prune);
        # the realistic client sends both fields together.
        consult = info.data.get("consultation_types")
        canonical: set[str] = set(_DEFAULT_CONSULTATION_TYPES)
        if consult:
            canonical.update(consult)
        pruned: dict[str, list[VisitTypeContext]] = {}
        for key, contexts in v.items():
            if key not in canonical:
                # Orphan visit type — drop the key and its contexts.
                continue
            if len(contexts) > _MAX_CONTEXTS_PER_VISIT_TYPE:
                raise ValueError(
                    f"max {_MAX_CONTEXTS_PER_VISIT_TYPE} contexts per "
                    "visit type"
                )
            # At most one default context per visit type (#577). The
            # per-context validator can't see siblings, so the count rule
            # lives here. Reject (not silently drop) so a confused client
            # can't half-apply intent; value not echoed.
            if sum(1 for c in contexts if c.is_default) > 1:
                raise ValueError(
                    "at most one default context per visit type"
                )
            pruned[key] = contexts
        return pruned


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's profile. Auto-creates with defaults on first call."""
    profile = await get_or_create_profile(
        db, clinician_id=user.user_id, display_name=user.email
    )
    return _to_response(profile)


@router.put("", response_model=ProfileResponse)
async def update_profile_route(
    body: UpdateProfileRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's profile fields."""
    # Ensure profile exists. Snapshot the pre-update team list so the
    # audit-row count delta below reflects the actual change, not the
    # post-write state.
    existing = await get_or_create_profile(
        db, clinician_id=user.user_id, display_name=user.email
    )

    # GH-318 / B3 — validate every custom-template pointer BEFORE any
    # write. A ``template_ref`` must be a ``custom_templates`` row that
    # exists AND is owned by the calling clinician; a malformed, missing,
    # or non-owned ref is REJECTED (422), never silently dropped. The 422
    # detail is reason-only — the ref value never echoes (a non-owner
    # could otherwise probe another clinician's template ids). The
    # ``VisitTypeContext`` model already enforced mutual exclusion with
    # ``template_key`` during parsing.
    if body.contexts_per_visit_type is not None:
        await _validate_template_refs(
            body.contexts_per_visit_type, owner_id=user.user_id, db=db
        )

    team_before_count: Optional[int] = None
    if body.allied_health_team is not None:
        try:
            team_before_count = len(json.loads(existing.allied_health_team))
        except (TypeError, ValueError):
            # Defensive — the column is `NOT NULL DEFAULT "[]"` so this
            # should never trip, but a bad legacy row shouldn't crash
            # the update path. Fall back to "no signal" and skip the
            # emit; the change still goes through.
            team_before_count = None

    # GH-259 — snapshot the pre-update consultation types list to compute
    # the count deltas the audit row carries. Like `team_before_count`
    # above, a parse failure on a legacy row falls back to "no signal"
    # rather than crashing the update path.
    types_before: Optional[list[str]] = None
    if body.consultation_types is not None:
        try:
            raw = json.loads(existing.consultation_types)
            if isinstance(raw, list):
                types_before = [t for t in raw if isinstance(t, str)]
        except (TypeError, ValueError):
            types_before = None

    # GH-313 — snapshot the pre-update contexts map for the audit diff
    # below. Same "no signal → skip emit" fallback as the lists above.
    contexts_before: Optional[dict] = None
    if body.contexts_per_visit_type is not None:
        try:
            raw_ctx = json.loads(
                getattr(existing, "contexts_per_visit_type", None) or "{}"
            )
            if isinstance(raw_ctx, dict):
                contexts_before = raw_ctx
        except (TypeError, ValueError):
            contexts_before = None

    updates = body.model_dump(exclude_none=True)

    # GH-313 — serialize contexts WITHOUT exclude_none so the stored shape
    # keeps the explicit null ``template_key`` / ``template_ref`` keys the
    # clients read back (a recursive ``exclude_none`` would drop them).
    # Built once here and reused for the audit diff below.
    contexts_after: Optional[dict] = None
    if body.contexts_per_visit_type is not None:
        contexts_after = {
            key: [ctx.model_dump() for ctx in contexts]
            for key, contexts in body.contexts_per_visit_type.items()
        }
        updates["contexts_per_visit_type"] = contexts_after

    profile = await update_profile(db, clinician_id=user.user_id, updates=updates)

    # GH-260 — emit TEAM_MEMBERS_UPDATED only when the count actually
    # changed. Same-content edits (re-order, rename in place) skip the
    # audit emit so the trail stays meaningful instead of noisy. Names
    # are deliberately NOT in the kwargs; see the docstring on the enum
    # member for the PHI rationale.
    if body.allied_health_team is not None and team_before_count is not None:
        team_after_count = len(body.allied_health_team)
        if team_before_count != team_after_count:
            await write_audit(
                _PROFILE_AUDIT_SESSION,
                AuditEventType.TEAM_MEMBERS_UPDATED,
                actor_id=str(user.user_id),
                members_count_before=team_before_count,
                members_count_after=team_after_count,
            )

    # GH-259 — emit PROFILE_CONSULTATION_TYPES_UPDATED with counts only
    # when the canonical list actually changed. Same-list edits skip the
    # emit so the trail stays meaningful. The four count deltas
    # (defaults/customs × added/removed) let the post-pilot review
    # answer "did clinicians use the feature?" without any labels
    # landing in the audit row. See the kwarg whitelist in
    # `audit_events.py::PROFILE_CONSULTATION_TYPES_UPDATED` for the
    # PHI-safety contract.
    if body.consultation_types is not None and types_before is not None:
        before = list(types_before)
        # `_validate_consultation_types` already de-duplicated, stripped,
        # and gated `body.consultation_types`. We re-read off the field
        # rather than the dumped `updates` dict so the pydantic-validated
        # form is what we diff against.
        after_canonical = body.consultation_types
        b_defaults, b_customs = _split_defaults_customs(before)
        a_defaults, a_customs = _split_defaults_customs(after_canonical)
        defaults_added = len(a_defaults - b_defaults)
        defaults_removed = len(b_defaults - a_defaults)
        customs_added = len(a_customs - b_customs)
        customs_removed = len(b_customs - a_customs)
        if (
            defaults_added
            or defaults_removed
            or customs_added
            or customs_removed
        ):
            await write_audit(
                _PROFILE_AUDIT_SESSION,
                AuditEventType.PROFILE_CONSULTATION_TYPES_UPDATED,
                actor_id=str(user.user_id),
                count_before=len(before),
                count_after=len(after_canonical),
                defaults_added=defaults_added,
                defaults_removed=defaults_removed,
                customs_added=customs_added,
                customs_removed=customs_removed,
            )

    # GH-313 / GH-318 — emit PROFILE_CONTEXTS_UPDATED with AGGREGATE
    # COUNTS ONLY, and only on a real diff. ``_diff_contexts`` keys
    # identity on the context id; the seven counts (incl. the B3
    # custom_templates_attached / custom_templates_detached pair) never
    # carry labels, keys, ids, or template names. See the kwarg whitelist
    # in `audit_events.py::PROFILE_CONTEXTS_UPDATED` for the PHI contract.
    if contexts_after is not None and contexts_before is not None:
        deltas = _diff_contexts(contexts_before, contexts_after)
        if any(deltas.values()):
            await write_audit(
                _PROFILE_AUDIT_SESSION,
                AuditEventType.PROFILE_CONTEXTS_UPDATED,
                actor_id=str(user.user_id),
                **deltas,
            )

    return _to_response(profile)


@router.get("/templates")
async def get_profile_templates(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's preferred templates as full template objects."""
    templates = await get_preferred_template_objects(db, clinician_id=user.user_id)
    return templates


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _validate_template_refs(
    contexts_per_visit_type: dict[str, list[VisitTypeContext]],
    *,
    owner_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Reject any ``template_ref`` that isn't an owned OR shared existing
    custom template (#318 / B3; shared refs enabled for the visit-type map).

    Gathers the distinct ``template_ref`` values across every context in the
    request and verifies each is owned by ``owner_id`` OR shared (an org/Library
    template) — mirroring the note-gen resolve path. Raises
    ``HTTPException(422)`` on the first failure — malformed UUID, nonexistent
    row, or a PRIVATE row owned by someone else (the lookup collapses "not
    found" and "not-yours-and-not-shared" into one result, so a non-owner can't
    probe another clinician's private templates). The detail string is
    reason-only: the rejected ref never rides along.
    """
    refs = {
        ctx.template_ref
        for contexts in contexts_per_visit_type.values()
        for ctx in contexts
        if ctx.template_ref
    }
    for ref in refs:
        try:
            ref_uuid = uuid.UUID(ref)
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(
                status_code=422,
                detail="template_ref is not a valid custom template reference",
            )
        # Owned OR shared: a clinician may pin their own custom template OR a
        # SHARED org/Library template (its whole purpose). A non-owned PRIVATE
        # template still resolves to None here → rejected (no cross-tenant leak).
        resolved = await custom_templates_service.get_owned_or_shared(
            ref_uuid, owner_id, db
        )
        if resolved is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "template_ref does not reference an owned or shared "
                    "custom template"
                ),
            )


def _diff_contexts(
    before: dict[str, list[dict]],
    after: dict[str, list[dict]],
) -> dict[str, int]:
    """Aggregate, PHI-free count deltas between two context maps (#313).

    Identity is the context ``id`` (stable across an in-place edit).
    Returns exactly the seven whitelisted ``PROFILE_CONTEXTS_UPDATED``
    counts — NEVER labels, visit-type keys, ids, or template names:

      * ``visit_types_touched`` — visit-type keys whose normalized
        context list changed (covers label edits + template swaps +
        add/remove + key add/remove).
      * ``contexts_added`` / ``contexts_removed`` — net context-id churn.
      * ``templates_attached`` — contexts that gained a built-in
        template_key (None → set, including brand-new contexts that ship
        with one).
      * ``templates_detached`` — contexts that lost a built-in
        template_key (set → None, including removed contexts that had one).
      * ``custom_templates_attached`` — contexts that gained a custom
        ``template_ref`` (None → set), the #318 / B3 mirror of
        ``templates_attached``.
      * ``custom_templates_detached`` — contexts that lost a custom
        ``template_ref`` (set → None).
    """

    def _by_id(
        m: dict[str, list[dict]],
    ) -> dict[str, tuple[Optional[str], Optional[str]]]:
        # id → (template_key, template_ref), flattened across visit types.
        out: dict[str, tuple[Optional[str], Optional[str]]] = {}
        for contexts in m.values():
            for ctx in contexts:
                cid = ctx.get("id")
                if isinstance(cid, str) and cid:
                    out[cid] = (ctx.get("template_key"), ctx.get("template_ref"))
        return out

    def _norm(contexts: list[dict]) -> list[tuple]:
        return [
            (
                c.get("id"),
                c.get("label"),
                c.get("template_key"),
                c.get("template_ref"),
            )
            for c in contexts
        ]

    before_ids = _by_id(before)
    after_ids = _by_id(after)

    def _tk(entry: Optional[tuple]) -> Optional[str]:
        return entry[0] if entry else None

    def _tr(entry: Optional[tuple]) -> Optional[str]:
        return entry[1] if entry else None

    contexts_added = len(set(after_ids) - set(before_ids))
    contexts_removed = len(set(before_ids) - set(after_ids))

    templates_attached = sum(
        1
        for cid, (tk, _tr_) in after_ids.items()
        if tk is not None and _tk(before_ids.get(cid)) is None
    )
    templates_detached = sum(
        1
        for cid, (tk, _tr_) in before_ids.items()
        if tk is not None and _tk(after_ids.get(cid)) is None
    )

    custom_templates_attached = sum(
        1
        for cid, (_tk_, tr) in after_ids.items()
        if tr is not None and _tr(before_ids.get(cid)) is None
    )
    custom_templates_detached = sum(
        1
        for cid, (_tk_, tr) in before_ids.items()
        if tr is not None and _tr(after_ids.get(cid)) is None
    )

    visit_types_touched = sum(
        1
        for key in set(before) | set(after)
        if _norm(before.get(key, [])) != _norm(after.get(key, []))
    )

    return {
        "visit_types_touched": visit_types_touched,
        "contexts_added": contexts_added,
        "contexts_removed": contexts_removed,
        "templates_attached": templates_attached,
        "templates_detached": templates_detached,
        "custom_templates_attached": custom_templates_attached,
        "custom_templates_detached": custom_templates_detached,
    }


def _annotate_team_presence(team: list[dict]) -> list[dict]:
    """Annotate each allied-health member with an effective "present
    today" flag (#275 / B4).

    Effective presence is ``present_today is True AND present_today_date
    == today`` (server-local date). A stale ``present_today_date`` (a flag
    left on from a previous day) reads as absent — this IS the daily
    auto-reset: no cron, the staleness check does it on every READ. The
    derived flag is surfaced as ``present_today_effective`` so the iOS
    picker can filter the day roster while the raw stored ``present_today``
    / ``present_today_date`` keys remain round-trippable for the editor.

    Non-dict entries (defensive against a malformed legacy row) pass
    through untouched. No PHI is read or written here.
    """
    today = date.today().isoformat()
    annotated: list[dict] = []
    for member in team:
        if not isinstance(member, dict):
            annotated.append(member)
            continue
        m = dict(member)
        m["present_today_effective"] = (
            bool(m.get("present_today"))
            and m.get("present_today_date") == today
        )
        annotated.append(m)
    return annotated


def _to_response(profile) -> ProfileResponse:
    return ProfileResponse(
        clinician_id=str(profile.clinician_id),
        display_name=profile.display_name,
        practice_type=profile.practice_type,
        primary_specialty=profile.primary_specialty,
        preferred_templates=json.loads(profile.preferred_templates),
        consultation_types=json.loads(profile.consultation_types),
        contexts_per_visit_type=json.loads(
            getattr(profile, "contexts_per_visit_type", None) or "{}"
        ),
        allied_health_team=_annotate_team_presence(
            json.loads(profile.allied_health_team)
        ),
        output_language=profile.output_language,
        ui_theme=getattr(profile, "ui_theme", "system"),
        accent_color=getattr(profile, "accent_color", "gold"),
        ui_language=getattr(profile, "ui_language", "en"),
        auto_upload=getattr(profile, "auto_upload", True),
        retention_days=getattr(profile, "retention_days", 7),
        consent_reprompt=getattr(profile, "consent_reprompt", "every_session"),
    )
