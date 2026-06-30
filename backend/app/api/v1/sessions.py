"""Session API routes — create, consent, start, pause, resume, stop.

No business logic here — routes call module service functions only.
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import (
    _load_transcript,
    get_owned_session_or_404,
    require_state,
    write_audit,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.identifier_hash import hash_identifier
from app.core.kms_encryption import decrypt_str, encrypt_str
from app.core.models import Stage2JobModel
from app.core.text_validation import validate_user_text
from app.core.types import SessionState
from app.modules.auth.service import (
    CurrentUser,
    get_current_user,
    require_prompt_testing,
)
from app.modules.config.appconfig_client import get_config
from app.modules.config.schema import (
    NoteGenerationProviderKey,
    TranscriptionProviderKey,
    VisionProviderKey,
    VisualEvidenceMode,
)
from app.modules.note_gen.service import (
    EmptyTranscriptError,
    generate_stage1_note,
)
from app.modules.session.service import (
    ConsentRequiredError,
    InvalidTransitionError,
    confirm_consent,
    create_session,
    delete_session,
    get_audit_event_for_state,
    list_sessions,
    resolve_context_template_key,
    transition_session,
)

logger = logging.getLogger("aurion.api.sessions")

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Request/Response Schemas ──────────────────────────────────────────────

class SessionParticipantRequest(BaseModel):
    """One person present at the encounter (#275).

    ``source`` distinguishes how the chip was added on the iOS sheet:
      * ``profile``      — picked from the clinician's saved allied-health
        roster. A ``name`` is required (the saved member is named) and
        ``is_persistent`` is forced ``True``.
      * ``adhoc_named``  — typed in for this encounter only, WITH a name.
      * ``adhoc_role``   — an anonymous role chip ("a nurse was present")
        carrying NO name — zero PHI. ``name`` MUST be null/empty; it is
        normalized to ``None`` so the attribution wire never synthesizes a
        name for an unnamed speaker (descriptive-mode / citation
        traceability — see ``render_participants_block``).

    Per-member access control is explicitly OUT OF SCOPE for #275 — these
    chips drive prompt attribution + the day-roster picker only.
    """

    name: Optional[str] = None  # null = anonymous role chip
    role: str
    source: Literal["profile", "adhoc_named", "adhoc_role"] = "adhoc_named"
    is_persistent: bool = False

    @model_validator(mode="after")
    def _normalize_source(self) -> "SessionParticipantRequest":
        stripped = (self.name or "").strip()
        if self.source == "adhoc_role":
            # Anonymous role chip — a name here is a contract violation
            # (the whole point is zero PHI). Reject rather than silently
            # drop so a buggy client surfaces it as a 422.
            if stripped:
                raise ValueError(
                    "adhoc_role participants must not carry a name"
                )
            self.name = None
        elif self.source == "profile":
            if not stripped:
                raise ValueError("profile participants require a name")
            self.name = stripped
        else:  # adhoc_named
            # Empty name on a named chip degrades to None rather than
            # persisting "" — keeps the attribution renderer's
            # name-present check honest.
            self.name = stripped or None
        # is_persistent is a derived flag: only roster-sourced members
        # persist back to the profile. Normalize here so the stored
        # participants_json is internally consistent regardless of what
        # the client sent.
        self.is_persistent = self.source == "profile"
        return self


class ProviderOverridesSchema(BaseModel):
    """Per-session provider routing overrides.

    The dict on the session row historically accepted any keys (untyped
    `Optional[dict]`). P1-7 closes the surface to the documented set so
    typos and unsupported keys are rejected at the API boundary instead
    of silently no-oping inside the registry.

    Closed key set (extra="forbid"):
      - `transcription`, `note_generation`, `vision`, `vision_clip`: per-
        session provider routing (level-3 switching per CLAUDE.md
        "Switching" table). Optional, no validation against the active
        provider catalog at this layer — the registry surfaces unknown
        provider strings as a 503 at dispatch time.
      - `visual_evidence_mode`: per-session dual-mode flip. Typed
        against the canonical `VisualEvidenceMode` enum so the route
        rejects unknown values (e.g. `"clip_only"` typo) with 422.

    Storage is JSON-encoded on `sessions.provider_overrides` (TEXT
    column). `_to_response` deserializes back to a plain dict for the
    client so the contract is round-trippable.
    """

    model_config = ConfigDict(extra="forbid")

    transcription: Optional[TranscriptionProviderKey] = None
    note_generation: Optional[NoteGenerationProviderKey] = None
    vision: Optional[VisionProviderKey] = None
    vision_clip: Optional[VisionProviderKey] = None
    visual_evidence_mode: Optional[VisualEvidenceMode] = None


class CreateSessionRequest(BaseModel):
    specialty: str
    consultation_type: Optional[str] = None
    encounter_context: Optional[str] = None
    # Visit Type → Context → Template (#314 / B2). The ``ctx_<8hex>`` id of
    # the context the clinician chose on the iOS context sheet, drawn from
    # their profile's ``contexts_per_visit_type`` map (B1 / #313). Optional
    # — old clients omit it and the session falls back to the specialty
    # default. ``encounter_context`` (free-text / chosen-context label for
    # the prompt block) is unchanged and orthogonal to this id.
    context_id: Optional[str] = None
    output_language: str = "en"
    encounter_type: str = "doctor_patient"
    participants: Optional[list[SessionParticipantRequest]] = None
    provider_overrides: Optional[ProviderOverridesSchema] = None
    capture_mode: str = "multimodal"


class SessionResponse(BaseModel):
    id: uuid.UUID
    clinician_id: uuid.UUID
    specialty: str
    state: str
    encounter_type: str = "doctor_patient"
    capture_mode: str = "multimodal"
    # Session provenance (VID-01/09): "video_upload" for web-portal video
    # imports, None/absent for live iOS captures. Drives the "Uploaded" badge
    # in the portal session lists. Not PHI.
    import_source: Optional[str] = None
    # Optional PHI identifier set by the clinician to link this session
    # back to their own patient roster (MRN hash, EMR encounter id, free
    # text — whatever the clinic uses). Decrypted server-side and only
    # populated for the owner of the row. Other CLINICIAN callers get a
    # 404 on the session entirely; admin/compliance get the row but with
    # this field omitted (we don't surface decrypted PHI cross-clinician).
    external_reference_id: Optional[str] = None
    # Round-trippable view of `sessions.provider_overrides` (P1-7). The
    # row stores a JSON-encoded dict; the response surfaces it as a
    # structured object so the iOS dispatcher can read
    # `visual_evidence_mode` and route Stage 2 evidence without a
    # second call. `None` when no overrides were set at creation.
    provider_overrides: Optional[dict] = None
    # Round-trippable view of `sessions.participants_json` (#275). The row
    # stores a JSON-encoded list of participant dicts ({name, role,
    # source, is_persistent}); the response surfaces it so the owning
    # clinician's client can re-render the chips it set at create time.
    # Owner-gated exactly like `external_reference_id` — `_to_response`
    # only ever runs against the caller's own row (see its docstring),
    # and admin/eval cross-clinician views use a separate response shape
    # (`EvalSessionResponse`) that never carries participants. Anonymous
    # role chips (`name: null`) carry zero PHI. `None` when none were set.
    participants: Optional[list[dict]] = None
    # Display-only signal (not a session state): True when the session is in
    # PROCESSING_STAGE2 AND its latest Stage 2 job has completed — i.e. the
    # full multimodal note is ready and the only remaining step is the
    # physician's manual final approval. The session genuinely rests in
    # PROCESSING_STAGE2 (final approval is a human boundary), so this is NOT a
    # state-machine change; it just lets clients render "Ready for review"
    # instead of "Processing/Enriching" for a finished-but-unapproved note
    # (the case that left two web-imported sessions looking stuck). Defaults
    # False, so older clients and non-Stage-2 sessions are unaffected.
    stage2_review_ready: bool = False
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── Patient identifier format gates ───────────────────────────────────────
#
# AC-4 of issue #161 — refuse to encrypt values that obviously aren't
# clinic identifiers. The intent is fail-closed against the most common
# foot-guns (a clinician pastes the patient's full name, email, or
# SSN into the chip) without trying to validate every imaginable MRN
# scheme. Four explicit deny patterns + a length cap is the design.
#
# These rules are mirrored client-side in
# `web/components/portal/PatientIdentifierEditor.tsx::validateIdentifier`
# so the portal surfaces the failure before the round trip. The
# server-side enforcement is the source of truth — never trust the
# client to gate PHI.
#
# Importantly, the rejection error string NEVER carries the rejected
# value itself (the value is itself sensitive — could be a full
# patient name). The reason code is short and reason-only.

_MAX_IDENTIFIER_LEN = 64


def _check_identifier_format(value: str) -> None:
    """Raise ValueError if the value looks like PHI we shouldn't store
    encrypted as a patient identifier.

    Thin wrapper around ``validate_user_text`` (``core.text_validation``)
    which carries the actual regex + token-shape gates. The wrapper
    exists because Pydantic surfaces the raised ``ValueError`` verbatim
    as the 422 detail, and historic test fixtures + the iOS / portal
    error catalogs assert against the noun "identifier" rather than
    the generic "text". Rewriting the message preserves the existing
    contract without re-implementing the gates.

    Pydantic catches ValueError and surfaces it as 422 unprocessable
    entity. The error string is short and reason-only — NEVER includes
    the rejected value. See ``ExternalReferenceIdRequest`` below for
    the `hide_input_in_errors=True` belt that keeps it out of
    `input_value` too.
    """
    try:
        validate_user_text(
            value, max_length=_MAX_IDENTIFIER_LEN, reject_full_name=True
        )
    except ValueError as exc:
        # Preserve the noun the patient-identifier catalogs were built
        # against — the messages are otherwise identical to the shared
        # helper. Keeps existing tests + the portal/iOS i18n strings
        # untouched.
        msg = str(exc).replace("text", "identifier", 1)
        raise ValueError(msg) from None


class ExternalReferenceIdRequest(BaseModel):
    """Patch body for setting / clearing the patient identifier.

    Empty string or null clears the column; any other string is encrypted
    via KMS and stored as bytea.

    Format validation is fail-closed against four explicit deny
    patterns — raw SSN, dashed SSN, email, full-name shape — plus a
    64-char cap. Clinics use a lot of different MRN schemes; we
    don't try to validate every one, only the obvious foot-guns.
    See `_check_identifier_format` above.

    `hide_input_in_errors=True` is load-bearing: it keeps the
    rejected value out of Pydantic's `ValidationError` string +
    `input_value` field. Without it, a 422 response (and any
    FastAPI/Sentry serialization of the error) would echo the raw
    identifier back, which lands PHI in observability surfaces we
    don't want it on.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    external_reference_id: Optional[str] = None

    @field_validator("external_reference_id")
    @classmethod
    def _validate_format(cls, v: Optional[str]) -> Optional[str]:
        # Null / blank clears the column — no format checks apply on
        # the empty path. The route handler does the strip-and-clear.
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            return v
        _check_identifier_format(stripped)
        return v


# ── Routes ────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_session_route(
    body: CreateSessionRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Pull the feature flag once. The route fast-fails before the row is
    # written if the caller asked for a visual_evidence_mode override
    # while the flag is off — the alternative (writing the row anyway,
    # ignoring the override at dispatch) would silently drop the
    # eval-team's intent and skew Phase 2 measurements.
    overrides_dict: Optional[dict] = None
    visual_evidence_mode_override: Optional[VisualEvidenceMode] = None
    if body.provider_overrides is not None:
        # mode="json" so enum values serialize to their string form and
        # the persisted JSON matches what the iOS client decodes.
        overrides_dict = body.provider_overrides.model_dump(
            mode="json", exclude_none=True
        )
        visual_evidence_mode_override = body.provider_overrides.visual_evidence_mode
        if visual_evidence_mode_override is not None:
            cfg = get_config()
            if not cfg.feature_flags.per_session_visual_evidence_mode_override:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "per-session visual_evidence_mode override is "
                        "disabled in this environment"
                    ),
                )

    # Visit Type → Context → Template (#314 / B2; #318 / B3). Resolve +
    # validate the chosen context's template ONCE here so the snapshot on
    # the row is deterministic at Stage 1 even if the profile is edited
    # mid-encounter. The context binds EITHER a built-in template_key OR a
    # custom template_ref (resolved to an owned custom_template_id). Never
    # raises — any "can't resolve" path returns the specialty-default
    # sentinel (None, None). A stale pin (built-in no longer available, or a
    # custom ref now deleted / unowned) is coerced to the default and
    # flagged for a count-only audit note below.
    (
        resolved_template_key,
        resolved_custom_template_id,
        template_key_coerced,
    ) = await resolve_context_template_key(
        db=db,
        clinician_id=user.user_id,
        consultation_type=body.consultation_type,
        context_id=body.context_id,
    )

    session = await create_session(
        db=db,
        clinician_id=user.user_id,
        specialty=body.specialty,
        consultation_type=body.consultation_type,
        encounter_context=body.encounter_context,
        output_language=body.output_language,
        encounter_type=body.encounter_type,
        participants=[p.model_dump() for p in body.participants] if body.participants else None,
        provider_overrides=overrides_dict,
        capture_mode=body.capture_mode,
        context_id=body.context_id,
        template_key=resolved_template_key,
        custom_template_id=resolved_custom_template_id,
    )
    await write_audit(
        session.id,
        AuditEventType.SESSION_CREATED,
        clinician_id=str(user.user_id),
        specialty=body.specialty,
    )
    # Count-only note when a chosen context pinned a template that no
    # longer resolves — a built-in key removed from disk OR a custom
    # template_ref now deleted / unowned (#318 / B3). The snapshot fell
    # back to the specialty default. No kwargs: never the context id,
    # template name, ref, or visit-type label.
    if template_key_coerced:
        await write_audit(
            session.id,
            AuditEventType.SESSION_TEMPLATE_KEY_COERCED,
        )
    # Separate audit row for the visual_evidence_mode override so the
    # eval-team's Phase 2 query (find every session that opted into a
    # non-default mode) is a single event-type filter against the
    # immutable log. The kwargs whitelist is enforced — see
    # ALLOWED_AUDIT_KWARGS for VISUAL_EVIDENCE_MODE_OVERRIDE_SET.
    if visual_evidence_mode_override is not None:
        await write_audit(
            session.id,
            AuditEventType.VISUAL_EVIDENCE_MODE_OVERRIDE_SET,
            actor_id=str(user.user_id),
            actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
            mode=visual_evidence_mode_override.value,
        )
    return _to_response(session)


ConsentMethod = Literal["verbal", "paper_form", "digital_form"]


class ConfirmConsentRequest(BaseModel):
    consent_method: ConsentMethod


@router.post("/{session_id}/consent", response_model=SessionResponse)
async def confirm_consent_route(
    session_id: uuid.UUID,
    body: ConfirmConsentRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    await confirm_consent(db, session)
    await write_audit(
        session.id,
        AuditEventType.CONSENT_CONFIRMED,
        consent_method=body.consent_method,
    )
    return _to_response(session)


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_recording_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.RECORDING)


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def pause_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.PAUSED)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.RECORDING)


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_recording_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    return await _do_transition(db, session, SessionState.PROCESSING_STAGE1)


class UpdateTemplateRequest(BaseModel):
    specialty: str


@router.patch("/{session_id}/template", response_model=SessionResponse)
async def update_session_template(
    session_id: uuid.UUID,
    body: UpdateTemplateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the session specialty/template after recording, before note generation.

    Only valid when the session is in PROCESSING_STAGE1 state (audio submitted
    but note not yet generated).
    """
    session = await get_owned_session_or_404(db, session_id, user)
    require_state(session, SessionState.PROCESSING_STAGE1)
    session.specialty = body.specialty
    await db.flush()

    await write_audit(session.id, AuditEventType.TEMPLATE_CHANGED, new_specialty=body.specialty)
    return _to_response(session)


@router.patch(
    "/{session_id}/identifier", response_model=SessionResponse
)
async def set_session_external_reference_id(
    session_id: uuid.UUID,
    body: ExternalReferenceIdRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the patient identifier (external_reference_id) on a session.

    The identifier is PHI: KMS-encrypted at rest, never logged in
    plaintext, never returned to non-owner callers. Empty string or
    null clears the column (and emits an audit event with
    `cleared=True` so the trail captures the deletion).

    Owner-only — non-owner CLINICIAN gets 404 from get_owned_session_or_404.
    """
    session = await get_owned_session_or_404(db, session_id, user)
    raw = (body.external_reference_id or "").strip()
    cleared = not raw
    if cleared:
        session.external_reference_id_encrypted = None
        session.external_reference_id_hash = None
    else:
        session.external_reference_id_encrypted = encrypt_str(raw)
        # Recompute the deterministic hash alongside the ciphertext so
        # the indexed lookup (#61) and the rail (#61 foundation) stay
        # in lockstep. Both columns are NULL together / non-NULL
        # together; the longitudinal-context query filters on the hash
        # column directly and would silently miss any row that has
        # ciphertext but no hash.
        session.external_reference_id_hash = hash_identifier(raw)
    await db.flush()

    # Audit row carries only the bool — never the identifier value
    # itself. The audit log is append-only; leaking PHI there would
    # be permanent.
    await write_audit(
        session.id,
        AuditEventType.EXTERNAL_REFERENCE_ID_SET,
        actor_id=str(user.user_id),
        cleared=cleared,
    )
    return _to_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session_or_404(db, session_id, user)
    ready = await _review_ready_session_ids(db, [session])
    return _to_response(session, review_ready=session.id in ready)


@router.get("", response_model=list[SessionResponse])
async def list_sessions_route(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await list_sessions(db, clinician_id=user.user_id)
    ready = await _review_ready_session_ids(db, sessions)
    return [_to_response(s, review_ready=s.id in ready) for s in sessions]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_session_route(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a session and all of its data.

    Clinician-scoped self-service cleanup (e.g. clearing a session that
    got wedged in PROCESSING_STAGE1 after a failed Stage 1). The caller may
    only discard their own sessions — another clinician's session 404s so
    its existence isn't revealed. Removes the session plus its transcript /
    note-version / pilot-metric / stage-2 rows.

    The DynamoDB audit trail is append-only and is NOT erased: a
    ``session_discarded`` event is written instead, after the delete is
    durably committed, so the record of the deletion survives.
    """
    # get_owned_session_or_404 already enforces ownership (clinician must
    # match; 404 leaks nothing about other clinicians' sessions).
    session = await get_owned_session_or_404(db, session_id, user)
    prior_state = (
        session.state.value
        if isinstance(session.state, SessionState)
        else str(session.state)
    )
    await delete_session(db, session)
    await db.commit()
    await write_audit(
        session_id, AuditEventType.SESSION_DISCARDED, prior_state=prior_state
    )


# ── Helpers ───────────────────────────────────────────────────────────────

async def _do_transition(db, session, target_state: SessionState) -> SessionResponse:
    try:
        session = await transition_session(db, session, target_state)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConsentRequiredError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await write_audit(session.id, get_audit_event_for_state(target_state))
    return _to_response(session)


# ── Regenerate note (#590) ─────────────────────────────────────────────────


class RegenerateNoteRequest(BaseModel):
    """Re-run Stage-1 note generation on the STORED transcript with a different
    template (#590). Set ``template_key`` (a built-in) OR ``custom_template_id``
    (an owned/shared custom template); if both are set the built-in wins, and if
    both are omitted the session's specialty default applies."""

    template_key: Optional[str] = None
    custom_template_id: Optional[uuid.UUID] = None


class RegenerateNoteResponse(BaseModel):
    version: int
    stage: int
    completeness_score: float
    provider_used: str


@router.post(
    "/{session_id}/regenerate-note", response_model=RegenerateNoteResponse
)
async def regenerate_note(
    session_id: uuid.UUID,
    body: RegenerateNoteRequest,
    user: CurrentUser = Depends(require_prompt_testing),
    db: AsyncSession = Depends(get_db),
) -> RegenerateNoteResponse:
    """Re-run Stage-1 note generation on an already-uploaded encounter with a
    different template — no re-upload, no re-transcribe (#590).

    Gated by ``require_prompt_testing`` (the per-user, admin-assignable
    capability; role-agnostic) and owner-scoped to the caller's own session.
    Reuses the persisted transcript + ``generate_stage1_note`` (template
    resolution + prompt cascade + auto-versioning), so a re-run is a cheap
    note-gen call on stored data — the expensive extraction isn't repeated.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    # Own-scope a custom-template override (SECURITY): a caller may regenerate
    # with their OWN custom template or a shared/Library one — never another
    # clinician's private template. generate_stage1_note's resolver loads it by
    # id UNSCOPED, so access is gated here. 404 (not 403) hides existence.
    if body.custom_template_id is not None:
        from app.modules.custom_templates.service import get_owned_or_shared

        template = await get_owned_or_shared(
            body.custom_template_id, user.user_id, db
        )
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Custom template not found.",
            )

    # Reuse the persisted transcript — never re-transcribe.
    transcript = await _load_transcript(db, session_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No transcript for this session yet.",
        )

    try:
        note = await generate_stage1_note(
            transcript=transcript,
            specialty=session.specialty,
            session_id=str(session_id),
            db=db,
            template_key=body.template_key,
            custom_template_id=body.custom_template_id,
        )
    except EmptyTranscriptError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The stored transcript is empty.",
        )
    await db.commit()

    return RegenerateNoteResponse(
        version=note.version,
        stage=note.stage,
        completeness_score=note.completeness_score,
        provider_used=note.provider_used,
    )


async def _review_ready_session_ids(db: AsyncSession, sessions) -> set:
    """Session ids whose Stage 2 finished and now await final approval.

    A session is "review ready" when it is in PROCESSING_STAGE2 AND its
    latest ``stage2_jobs`` row is ``completed`` — the full note exists, only
    the physician's manual approval remains. One batched query for all
    PROCESSING_STAGE2 sessions (no N+1). Display-only — see
    ``SessionResponse.stage2_review_ready``.
    """
    candidates = [
        s.id
        for s in sessions
        if (
            s.state.value if isinstance(s.state, SessionState) else s.state
        )
        == SessionState.PROCESSING_STAGE2.value
    ]
    if not candidates:
        return set()
    rows = (
        await db.execute(
            select(
                Stage2JobModel.session_id,
                Stage2JobModel.status,
                Stage2JobModel.created_at,
            )
            .where(Stage2JobModel.session_id.in_(candidates))
            .order_by(
                Stage2JobModel.session_id,
                Stage2JobModel.created_at.desc(),
            )
        )
    ).all()
    latest_status: dict = {}
    for sid, st, _created in rows:
        # First row per session_id is the latest (created_at desc).
        if sid not in latest_status:
            latest_status[sid] = st
    return {sid for sid, st in latest_status.items() if st == "completed"}


def _to_response(session, review_ready: bool = False) -> SessionResponse:
    """Map a SessionModel row to its API response.

    Every caller in this module is reached only after ownership has been
    confirmed by `get_owned_session_or_404` (or filters to
    `clinician_id == user.user_id` for the list path), so it's safe to
    decrypt the identifier here unconditionally — there is no public
    surface where _to_response runs against another clinician's row.
    """
    external_id: Optional[str] = None
    if getattr(session, "external_reference_id_encrypted", None):
        try:
            external_id = decrypt_str(session.external_reference_id_encrypted)
        except Exception as exc:
            # Never crash the response on a decryption failure; log +
            # omit. If the KMS key rotated and old ciphertexts can't be
            # decrypted that's a CMK rotation incident, not a 500.
            logger.warning(
                "Failed to decrypt external_reference_id for session=%s: %s",
                session.id, exc,
            )
    # Deserialize the JSON-encoded provider_overrides column back to a
    # plain dict. Older rows pre-P1-7 used `str(dict)` which is NOT
    # valid JSON — those decode failures get swallowed and the field is
    # omitted (None) so the response path can't 500 on a stale row.
    overrides: Optional[dict] = None
    raw_overrides = getattr(session, "provider_overrides", None)
    if raw_overrides:
        try:
            parsed = _json.loads(raw_overrides)
            if isinstance(parsed, dict):
                overrides = parsed
        except (ValueError, TypeError):
            logger.warning(
                "Failed to decode provider_overrides JSON for session=%s "
                "(legacy str(dict) format?) — dropping from response",
                session.id,
            )

    # Deserialize the JSON-encoded participants list (#275) defensively,
    # exactly like provider_overrides above: parse, guard that it's a
    # list, and swallow any JSON error → None so a malformed legacy row
    # can never 500 the response path.
    participants: Optional[list[dict]] = None
    raw_participants = getattr(session, "participants_json", None)
    if raw_participants:
        try:
            parsed_participants = _json.loads(raw_participants)
            if isinstance(parsed_participants, list):
                participants = parsed_participants
        except (ValueError, TypeError):
            logger.warning(
                "Failed to decode participants_json for session=%s — "
                "dropping from response",
                session.id,
            )

    return SessionResponse(
        id=session.id,
        clinician_id=session.clinician_id,
        specialty=session.specialty,
        state=session.state.value if isinstance(session.state, SessionState) else session.state,
        encounter_type=session.encounter_type or "doctor_patient",
        capture_mode=getattr(session, "capture_mode", None) or "multimodal",
        import_source=getattr(session, "import_source", None),
        external_reference_id=external_id,
        provider_overrides=overrides,
        participants=participants,
        stage2_review_ready=review_ready,
        created_at=session.created_at.isoformat() if session.created_at else "",
        updated_at=session.updated_at.isoformat() if session.updated_at else "",
    )
