"""Client-origin audit events — receive device-authoritative provenance from iOS.

POST /api/v1/sessions/{session_id}/client-audit-events

Some audit provenance is known ONLY on the device and has no server-side
equivalent. The compliance-critical example (AUR-API-CLIENT-AUDIT) is the
masking FAILURE family: a video/screen/clip frame whose on-device masking
fails is dropped *fail-closed* and never uploaded, so the backend otherwise
has no record it ever existed. The PHI-masking report needs to prove those
frames were discarded, not leaked.

Security posture:
  * Only events in ``CLIENT_AUDIT_EVENTS`` may be posted — a deliberately
    narrow allow-list of device-authoritative, non-server-emitted events.
    This blocks a client from forging (or duplicating) server-authoritative
    events like ``consent_confirmed`` or ``frame_uploaded``.
  * The session must exist AND be owned by the caller (404 otherwise).
  * Field KEYS are hard-validated against ``ALLOWED_AUDIT_KWARGS`` and
    rejected with 422 — we do NOT rely on prod's warn-only strict mode for a
    client-facing surface, so an unwhitelisted key can't smuggle PHI into the
    immutable log. Values are bounded in count and length.

PHI-free by construction: the allow-listed events carry only a bounded
``failure_reason`` enum and integer counts — never an image, S3 key, or body.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, write_audit
from app.core.audit_events import (
    CLIENT_AUDIT_EVENTS,
    AuditEventType,
    validate_audit_kwargs,
)
from app.core.database import get_db
from app.modules.auth.service import CurrentUser, get_current_user

logger = logging.getLogger("aurion.api.client_audit")

router = APIRouter(prefix="/sessions", tags=["audit"])

# Bounds on the free-form ``fields`` map. The whitelist already constrains
# WHICH keys are allowed per event; these guard against an oversized/abusive
# body independent of the per-event whitelist.
_MAX_FIELDS = 16
_MAX_VALUE_LEN = 128


class ClientAuditEventRequest(BaseModel):
    event_type: str = Field(..., description="Must be a member of CLIENT_AUDIT_EVENTS")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="PHI-free string fields, validated against the event's whitelist",
    )


class ClientAuditEventResponse(BaseModel):
    recorded: bool
    event_type: str


@router.post(
    "/{session_id}/client-audit-events",
    response_model=ClientAuditEventResponse,
    status_code=202,
)
async def record_client_audit_event(
    session_id: uuid.UUID,
    body: ClientAuditEventRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClientAuditEventResponse:
    """Append one device-authoritative audit event to the session's trail."""
    await get_owned_session_or_404(db, session_id, user)

    try:
        event = AuditEventType(body.event_type)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown event_type")

    if event not in CLIENT_AUDIT_EVENTS:
        raise HTTPException(status_code=422, detail="event_type is not client-postable")

    if len(body.fields) > _MAX_FIELDS:
        raise HTTPException(status_code=422, detail="Too many fields")

    unknown = validate_audit_kwargs(event, body.fields.keys())
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unknown fields: {sorted(unknown)}"
        )

    for key, value in body.fields.items():
        if len(value) > _MAX_VALUE_LEN:
            raise HTTPException(status_code=422, detail=f"Field '{key}' too long")

    await write_audit(session_id, event, **body.fields)
    return ClientAuditEventResponse(recorded=True, event_type=event.value)
