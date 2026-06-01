"""Clinician self-scoped endpoints (``/api/v1/me/*``).

Companion to the existing ``/profile``, ``/sessions``, ``/notes`` routers.
These endpoints all act on resources owned by the calling clinician — never
on arbitrary rows — and back the web portal's clinician views.

Groups of endpoints:

  /me/audit                          — own audit log (DynamoDB row-filtered)
  /me/custom-templates               — CRUD over personal note templates
  /me/template-authoring             — conversational template builder
  /me/export-bulk                    — zip of multiple session DOCXs

CLINICIAN role is required at the dependency layer. Admin/compliance roles
that legitimately need a clinician's view do so via the existing
``/admin/*`` routes, which have their own auth gates.
"""

from __future__ import annotations

import io
import logging
import uuid
import zipfile
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin._shared import (
    PaginatedAuditResponse,
    apply_audit_filters,
    event_to_response,
    scan_audit_events,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.kms_encryption import decrypt_str
from app.core.models import (
    CustomTemplateModel,
    SessionModel,
    TemplateAuthoringSessionModel,
)
from app.core.types import ProviderError, SessionState, Template, UserRole
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.custom_templates import service as custom_templates_service
from app.modules.export.service import export_note_docx
from app.modules.macros import service as macros_service
from app.modules.note_gen.service import get_latest_note
from app.modules.template_authoring import service as template_authoring_service

logger = logging.getLogger("aurion.api.me")

router = APIRouter(prefix="/me", tags=["me"])


# ── Auth dependency ────────────────────────────────────────────────────────


async def get_current_clinician(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require CLINICIAN role for all ``/me/*`` endpoints.

    Admin / compliance / eval roles get 403 because the semantic of
    /me/* is "as this clinician, acting on their own data" — those
    other roles have richer admin equivalents under /admin/*.
    """
    if user.role != UserRole.CLINICIAN:
        raise HTTPException(
            status_code=403,
            detail=f"/me/* is for CLINICIAN role only (got {user.role.value})",
        )
    return user


@router.get("/_health", include_in_schema=False)
async def me_health(
    _user: CurrentUser = Depends(get_current_clinician),
) -> dict[str, str]:
    """Mounted-router liveness probe. Verifies the auth dependency works
    end-to-end (CLINICIAN sees `{ok: true}`; everyone else sees 403).
    Excluded from the public OpenAPI schema."""
    return {"ok": "true"}


# ── /me/audit ──────────────────────────────────────────────────────────────


@router.get("/audit", response_model=PaginatedAuditResponse)
async def get_my_audit_log(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_clinician),
) -> PaginatedAuditResponse:
    """Audit events involving the calling clinician.

    Filters on `actor_id == user.user_id` (or `clinician_id == ...`,
    same partition) so a clinician sees only the rows they generated —
    never another clinician's audit trail. This is the clinician-side
    mirror of `/admin/audit` which is COMPLIANCE/ADMIN-only and shows
    everyone.

    Pagination + filtering are identical to the admin endpoint so the
    web portal can reuse its table component verbatim.
    """
    audit = get_audit_log_service()
    if session_id:
        events = await audit.get_session_events(session_id)
    else:
        events = await scan_audit_events(audit)

    # The shared filter already accepts `clinician_id=...` and matches
    # against both `clinician_id` and `actor_id` fields on each row —
    # use the caller's own id as the filter so the result set is scoped
    # to their own actions even when admin events for the same session
    # are present.
    filtered = apply_audit_filters(
        events,
        clinician_id=str(user.user_id),
        date_from=date_from,
        date_to=date_to,
        event_type=event_type,
    )

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    return PaginatedAuditResponse(
        items=[event_to_response(e) for e in page_items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── /me/custom-templates ───────────────────────────────────────────────────


class CustomTemplateResponse(BaseModel):
    """API shape for a custom template row.

    Includes the parsed `template` dict so the frontend doesn't have to
    re-parse the embedded JSON column on every list render.
    """

    id: str
    key: str
    display_name: str
    version: str
    owner_id: str
    is_shared: bool
    template: dict[str, Any]
    created_at: str
    updated_at: str


class CustomTemplateCreateRequest(BaseModel):
    """Body for POST /me/custom-templates.

    `template` must satisfy the Template Pydantic schema. The service
    re-validates before insert, so a route-level Pydantic field of
    `dict` is sufficient (we only ever raise a 422 from the FastAPI
    layer if the JSON is malformed, not for schema violations — those
    surface as 400 from the service).
    """

    template: dict[str, Any] = Field(
        ..., description="Template JSON matching the Template schema"
    )


@router.get("/custom-templates", response_model=list[CustomTemplateResponse])
async def list_my_custom_templates(
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> list[CustomTemplateResponse]:
    """List the caller's own custom templates plus community-shared ones."""
    rows = await custom_templates_service.list_for_owner(
        user.user_id, db, include_shared=True
    )
    return [_to_custom_template_response(r) for r in rows]


@router.post(
    "/custom-templates",
    response_model=CustomTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_custom_template(
    body: CustomTemplateCreateRequest,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> CustomTemplateResponse:
    try:
        row = await custom_templates_service.create_for_owner(
            user.user_id, body.template, db
        )
    except custom_templates_service.CustomTemplateError as exc:
        msg = str(exc)
        status_code = 409 if "already exists" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)
    await db.commit()
    return _to_custom_template_response(row)


@router.patch(
    "/custom-templates/{template_id}", response_model=CustomTemplateResponse
)
async def update_my_custom_template(
    template_id: uuid.UUID,
    body: CustomTemplateCreateRequest,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> CustomTemplateResponse:
    row = await custom_templates_service.get_owned(template_id, user.user_id, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row = await custom_templates_service.update_owned(row, body.template, db)
    except custom_templates_service.CustomTemplateError as exc:
        msg = str(exc)
        status_code = 409 if "already exists" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)
    await db.commit()
    return _to_custom_template_response(row)


@router.delete(
    "/custom-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_my_custom_template(
    template_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await custom_templates_service.get_owned(template_id, user.user_id, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await custom_templates_service.delete_owned(row, db)
    await db.commit()


# ── /me/template-authoring (conversational builder) ────────────────────────


class _ChatMessageDTO(BaseModel):
    role: str
    content: str


class AuthoringSessionResponse(BaseModel):
    """API shape for a template authoring session.

    `draft_template` is the latest LLM-emitted valid draft (None until
    the assistant has produced one). `messages` is the full chat
    history including the bootstrap assistant message — the frontend
    renders it directly into the chat pane.
    """

    id: str
    status: str
    messages: list[_ChatMessageDTO]
    draft_template: Optional[dict[str, Any]]
    assistant_message: Optional[str] = Field(
        None,
        description=(
            "Convenience field — the most recent assistant turn. The "
            "frontend uses this to animate just the new bubble rather "
            "than re-rendering the whole pane."
        ),
    )


class AuthoringMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)


@router.post(
    "/template-authoring",
    response_model=AuthoringSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_template_authoring(
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> AuthoringSessionResponse:
    """Open a fresh conversational template-authoring session."""
    row, reply = await template_authoring_service.start_authoring_session(
        user.user_id, db
    )
    await db.commit()
    return _to_authoring_response(row, reply.assistant_message)


@router.get(
    "/template-authoring/{session_id}", response_model=AuthoringSessionResponse
)
async def get_template_authoring(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> AuthoringSessionResponse:
    """Resume an existing authoring session (e.g. another device)."""
    row = await template_authoring_service.get_authoring_session(
        session_id, user.user_id, db
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Authoring session not found")
    return _to_authoring_response(row, assistant_message=None)


@router.post(
    "/template-authoring/{session_id}", response_model=AuthoringSessionResponse
)
async def continue_template_authoring(
    session_id: uuid.UUID,
    body: AuthoringMessageRequest,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> AuthoringSessionResponse:
    """Append a user turn; returns the assistant reply + any new draft."""
    row = await template_authoring_service.get_authoring_session(
        session_id, user.user_id, db
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Authoring session not found")
    if row.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Authoring session is {row.status}, not active",
        )
    try:
        reply = await template_authoring_service.continue_authoring(
            row, body.message, db
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ProviderError as exc:
        # Surface upstream LLM failures (rate limits, auth errors,
        # transient timeouts) as 502 so the frontend can render a
        # clean retry affordance. Without this, ProviderError
        # propagates as an unhandled 500 — and FastAPI strips CORS
        # headers from 500s, so the browser sees only a misleading
        # CORS error instead of the actual upstream issue.
        logger.warning(
            "template-authoring continue: provider failed session=%s: %s",
            session_id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error: {exc}",
        )
    await db.commit()
    return _to_authoring_response(row, reply.assistant_message)


@router.post(
    "/template-authoring/{session_id}/finalize",
    response_model=CustomTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def finalize_template_authoring(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> CustomTemplateResponse:
    """Promote the current draft to a `custom_templates` row.

    Closes the authoring session (status='completed') but does not
    delete it — the conversation is part of the audit story for how
    the template came to exist.
    """
    row = await template_authoring_service.get_authoring_session(
        session_id, user.user_id, db
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Authoring session not found")
    try:
        custom = await template_authoring_service.finalize_authoring(row, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return _to_custom_template_response(custom)


@router.post(
    "/custom-templates/upload",
    response_model=AuthoringSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_template_for_extraction(
    document: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> AuthoringSessionResponse:
    """Upload a JSON / plain-text template document for LLM extraction.

    Always lands as an *authoring session* (not a finalized custom
    template) so the physician reviews the LLM's extraction and can
    refine via chat before saving. The frontend transitions straight
    from the file picker to the chat UI with the extracted draft
    pre-rendered in the preview card.
    """
    body = await document.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty document")

    # Best-effort decode; non-UTF-8 bytes (e.g. binary DOCX) survive
    # via `errors='ignore'` so the LLM at least sees readable text. A
    # full python-docx pre-parse for .docx → .txt is out of scope here
    # (PR-E can add it on the frontend side via a paste-as-text step).
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="ignore")
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Document has no extractable text")

    try:
        row, reply = await template_authoring_service.upload_template_document(
            user.user_id, text, db
        )
    except ProviderError as exc:
        # Same rationale as continue_template_authoring — surface
        # provider failures as 502 so CORS headers survive and the
        # frontend can show a real error.
        logger.warning("template-authoring upload: provider failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error: {exc}",
        )
    await db.commit()
    return _to_authoring_response(row, reply.assistant_message)


# ── /me/macros — physician phrase shortcuts ───────────────────────────────


class MacroResponse(BaseModel):
    id: str
    shortcut: str
    body: str
    specialty: Optional[str] = None
    is_shared: bool
    created_at: str
    updated_at: str


class MacroCreateRequest(BaseModel):
    shortcut: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    specialty: Optional[str] = None


class MacroUpdateRequest(BaseModel):
    """Partial update. Each field is optional; only the set fields are
    touched. `clear_specialty=true` removes the scope (you can't use
    `specialty=null` here because that already means no-change)."""

    shortcut: Optional[str] = None
    body: Optional[str] = None
    specialty: Optional[str] = None
    clear_specialty: bool = False


def _to_macro_response(row) -> MacroResponse:
    return MacroResponse(
        id=str(row.id),
        shortcut=row.shortcut,
        body=row.body,
        specialty=row.specialty,
        is_shared=row.is_shared,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/macros", response_model=list[MacroResponse])
async def list_my_macros(
    specialty: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> list[MacroResponse]:
    rows = await macros_service.list_for_owner(
        user.user_id, db, specialty=specialty
    )
    return [_to_macro_response(r) for r in rows]


@router.post(
    "/macros",
    response_model=MacroResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_macro(
    body: MacroCreateRequest,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> MacroResponse:
    try:
        row = await macros_service.create_for_owner(
            user.user_id, body.shortcut, body.body, db, specialty=body.specialty
        )
    except macros_service.MacroError as exc:
        msg = str(exc)
        status_code = 409 if "already exists" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(row.id),
        event_type=AuditEventType.MACRO_CREATED,
        actor_id=str(user.user_id),
        macro_id=str(row.id),
        shortcut=row.shortcut,
        specialty=row.specialty or "",
    )
    await db.commit()
    return _to_macro_response(row)


@router.patch("/macros/{macro_id}", response_model=MacroResponse)
async def update_my_macro(
    macro_id: uuid.UUID,
    body: MacroUpdateRequest,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> MacroResponse:
    row = await macros_service.get_owned(macro_id, user.user_id, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Macro not found")
    try:
        row = await macros_service.update_owned(
            row,
            db,
            shortcut=body.shortcut,
            body=body.body,
            specialty=body.specialty,
            clear_specialty=body.clear_specialty,
        )
    except macros_service.MacroError as exc:
        msg = str(exc)
        status_code = 409 if "already" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=str(row.id),
        event_type=AuditEventType.MACRO_UPDATED,
        actor_id=str(user.user_id),
        macro_id=str(row.id),
        shortcut=row.shortcut,
        specialty=row.specialty or "",
    )
    await db.commit()
    return _to_macro_response(row)


@router.delete(
    "/macros/{macro_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_my_macro(
    macro_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await macros_service.get_owned(macro_id, user.user_id, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Macro not found")
    shortcut = row.shortcut
    macro_id_str = str(row.id)
    await macros_service.delete_owned(row, db)

    audit = get_audit_log_service()
    await audit.write_event(
        session_id=macro_id_str,
        event_type=AuditEventType.MACRO_DELETED,
        actor_id=str(user.user_id),
        macro_id=macro_id_str,
        shortcut=shortcut,
    )
    await db.commit()


# ── /me/patients — longitudinal cross-encounter context ───────────────────


class PatientSessionMatch(BaseModel):
    """One match in the /me/patients/{identifier}/sessions response.

    Slim shape on purpose — the caller already has the session id and
    enough context (specialty, state, created_at) to render the
    'Previous encounters with this patient' list without a second hop.
    """

    session_id: str
    specialty: str
    state: str
    created_at: str


@router.get(
    "/patients/{identifier}/sessions",
    response_model=list[PatientSessionMatch],
)
async def list_my_sessions_by_patient_identifier(
    identifier: str,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> list[PatientSessionMatch]:
    """Return prior sessions tagged with the same patient identifier.

    Scoped to the calling clinician — we never reveal another clinician's
    sessions even when the identifier matches. Decrypts the identifier
    on each row to compare (no plaintext index column today; pilot scale
    makes the linear scan trivial). A future PR can add a deterministic
    hash column for indexed lookup if performance demands it.

    Empty/blank identifier → 422; comparison is exact-match
    case-sensitive (the same physician should reproduce the same
    identifier across encounters).
    """
    target = identifier.strip()
    if not target:
        raise HTTPException(
            status_code=422, detail="identifier must be non-empty"
        )

    stmt = select(SessionModel).where(
        SessionModel.clinician_id == user.user_id,
        SessionModel.external_reference_id_encrypted.is_not(None),
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    matches: list[PatientSessionMatch] = []
    for row in rows:
        try:
            plain = decrypt_str(row.external_reference_id_encrypted)
        except Exception:
            # Decryption failure on this row — skip + log; surfaces as
            # a CMK incident in the dashboards rather than crashing the
            # entire lookup.
            logger.warning(
                "Skip identifier match on session=%s (decrypt failed)", row.id
            )
            continue
        if plain == target:
            matches.append(
                PatientSessionMatch(
                    session_id=str(row.id),
                    specialty=row.specialty,
                    state=row.state.value if hasattr(row.state, "value") else str(row.state),
                    created_at=row.created_at.isoformat() if row.created_at else "",
                )
            )

    # Newest first so the consumer renders most-recent at the top.
    matches.sort(key=lambda m: m.created_at, reverse=True)
    return matches


# ── /me/export-bulk ────────────────────────────────────────────────────────


class BulkExportRequest(BaseModel):
    session_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=50)


@router.post("/export-bulk")
async def bulk_export(
    body: BulkExportRequest,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Zip up DOCX exports for multiple owned sessions.

    Each session in the body must be owned by the caller AND have an
    approved note (REVIEW_COMPLETE state). Non-owner / non-approved
    sessions are silently SKIPPED (logged) rather than aborting the
    whole zip — physicians can re-include them once they're ready.
    The audit log records the bulk-export event with the included
    session ids so the audit trail isn't ambiguous.

    Stream the zip as it's built — for 50 sessions this stays small
    (<10 MB typically) but the streaming pattern is correct and lets
    iOS-style clients consume without holding everything in browser
    memory.
    """
    sessions = await _load_owned_sessions(body.session_ids, user.user_id, db)
    if not sessions:
        raise HTTPException(
            status_code=400,
            detail="No included sessions are owned by you AND ready for export.",
        )

    buffer = io.BytesIO()
    included_ids: list[str] = []
    skipped_ids: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for session in sessions:
            if session.state != SessionState.REVIEW_COMPLETE and session.state != SessionState.EXPORTED:
                skipped_ids.append(str(session.id))
                continue
            note = await get_latest_note(str(session.id), db)
            if note is None:
                skipped_ids.append(str(session.id))
                continue
            try:
                docx_bytes = await export_note_docx(str(session.id), note, db)
            except Exception as exc:
                logger.warning(
                    "Bulk export skipped session=%s due to DOCX failure: %s",
                    session.id, exc,
                )
                skipped_ids.append(str(session.id))
                continue
            zf.writestr(f"aurion_note_{session.id}.docx", docx_bytes)
            included_ids.append(str(session.id))

    if not included_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "Bulk export produced an empty archive — every requested "
                "session was missing an approved note or failed to render."
            ),
        )

    # One audit event for the whole bulk action — the per-session
    # NOTE_EXPORTED events were already written by export_note_docx
    # for each successfully-rendered session, so the trail is
    # consistent without double-counting.
    audit = get_audit_log_service()
    await audit.write_event(
        session_id=included_ids[0],  # anchor on the first; bulk_ids carries the rest
        event_type=AuditEventType.BULK_NOTE_EXPORT,
        included_session_ids=included_ids,
        skipped_session_ids=skipped_ids,
        actor_id=str(user.user_id),
    )

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aurion_bulk_{len(included_ids)}_notes.zip"'
            ),
            "X-Included-Count": str(len(included_ids)),
            "X-Skipped-Count": str(len(skipped_ids)),
        },
    )


# ── Response helpers ───────────────────────────────────────────────────────


def _to_custom_template_response(row: CustomTemplateModel) -> CustomTemplateResponse:
    return CustomTemplateResponse(
        id=str(row.id),
        key=row.key,
        display_name=row.display_name,
        version=row.version,
        owner_id=str(row.owner_id),
        is_shared=row.is_shared,
        template=custom_templates_service.template_to_dict(row),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _to_authoring_response(
    row: TemplateAuthoringSessionModel,
    assistant_message: Optional[str],
) -> AuthoringSessionResponse:
    messages = template_authoring_service._decode_messages(row.messages_json)
    draft_template = None
    if row.draft_template_json:
        try:
            # Re-validate at the response boundary so a corrupt-on-disk
            # draft never leaks to the frontend.
            template = Template.model_validate_json(row.draft_template_json)
            draft_template = template.model_dump()
        except ValidationError:
            logger.error(
                "Authoring session %s has invalid draft JSON on disk", row.id
            )
    return AuthoringSessionResponse(
        id=str(row.id),
        status=row.status,
        messages=[_ChatMessageDTO(role=m.role, content=m.content) for m in messages],
        draft_template=draft_template,
        assistant_message=assistant_message,
    )


async def _load_owned_sessions(
    session_ids: list[uuid.UUID],
    owner_id: uuid.UUID,
    db: AsyncSession,
) -> list[SessionModel]:
    """Fetch every requested session, filtered to the caller's ownership.

    Non-owner ids are silently dropped (not surfaced) so a malicious
    caller can't enumerate other clinicians' session existence via
    bulk-export probing.
    """
    stmt = select(SessionModel).where(
        SessionModel.id.in_(session_ids),
        SessionModel.clinician_id == owner_id,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
