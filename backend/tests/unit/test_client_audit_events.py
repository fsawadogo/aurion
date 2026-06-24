"""AUR-API-CLIENT-AUDIT — the client-origin audit endpoint.

iOS posts device-authoritative masking-FAILURE provenance (dropped frames
that never upload, so the server has no other record they existed) to
``POST /sessions/{id}/client-audit-events``. The endpoint must:

  * accept only the narrow ``CLIENT_AUDIT_EVENTS`` allow-list — a client
    must not be able to forge or duplicate server-authoritative events;
  * hard-reject unknown/oversized fields with 422 (don't rely on prod's
    warn-only strict mode for a client-facing surface);
  * write the event for an owned session.

These call the handler directly with the session lookup + audit writer
patched, so no DynamoDB/LocalStack is needed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import client_audit
from app.api.v1.client_audit import (
    ClientAuditEventRequest,
    record_client_audit_event,
)
from app.core.audit_events import (
    CLIENT_AUDIT_EVENTS,
    AuditEventType,
)


async def _call(event_type: str, fields: dict[str, str] | None = None):
    body = ClientAuditEventRequest(event_type=event_type, fields=fields or {})
    user = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    with (
        patch.object(
            client_audit, "get_owned_session_or_404", new=AsyncMock()
        ) as owned,
        patch.object(client_audit, "write_audit", new=AsyncMock()) as writer,
    ):
        result = await record_client_audit_event(
            session_id=uuid.uuid4(), body=body, user=user, db=db
        )
    return result, owned, writer


# ── Allow-list shape ──────────────────────────────────────────────────────────


def test_client_allow_list_is_masking_failure_family() -> None:
    assert CLIENT_AUDIT_EVENTS == frozenset(
        {
            AuditEventType.MASKING_FAILED,
            AuditEventType.MASKING_FAILURE_RETRIED,
            AuditEventType.MASKING_FAILURE_SKIPPED,
        }
    )


def test_server_authoritative_events_not_client_postable() -> None:
    # A client must not be able to assert these — the server emits them.
    for forbidden in (
        AuditEventType.CONSENT_CONFIRMED,
        AuditEventType.FRAME_UPLOADED,
        AuditEventType.LOGIN_SUCCESS,
        AuditEventType.STAGE1_APPROVED,
        AuditEventType.MASKING_CONFIRMED,
    ):
        assert forbidden not in CLIENT_AUDIT_EVENTS


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_masking_failed_is_recorded() -> None:
    result, owned, writer = await _call(
        "masking_failed",
        {
            "frame_type": "clip",
            "failure_reason": "render_error",
            "frames_total": "30",
            "frames_with_faces": "4",
            "frames_failed": "1",
        },
    )
    assert result.recorded is True
    assert result.event_type == "masking_failed"
    owned.assert_awaited_once()  # ownership gate ran
    writer.assert_awaited_once()
    # The event + fields are passed through to the audit writer verbatim.
    _, kwargs = writer.await_args
    assert kwargs["frame_type"] == "clip"
    assert kwargs["failure_reason"] == "render_error"


@pytest.mark.asyncio
async def test_retried_count_only_is_recorded() -> None:
    result, _, writer = await _call("masking_failure_retried", {"frame_count": "3"})
    assert result.recorded is True
    writer.assert_awaited_once()


# ── Rejections ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_event_type_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        await _call("totally_made_up_event")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_non_client_postable_event_rejected() -> None:
    # A real, valid AuditEventType — but server-authoritative.
    with pytest.raises(HTTPException) as exc:
        await _call("consent_confirmed", {"consent_method": "verbal"})
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_unknown_field_key_rejected() -> None:
    # 'patient_name' is not in the masking_failed whitelist — hard reject so
    # a malicious client can't smuggle PHI into an unwhitelisted key.
    with pytest.raises(HTTPException) as exc:
        await _call("masking_failed", {"frame_type": "video", "patient_name": "X"})
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_oversized_field_value_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        await _call("masking_failed", {"failure_reason": "z" * 200})
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_too_many_fields_rejected() -> None:
    fields = {f"k{i}": "v" for i in range(20)}
    with pytest.raises(HTTPException) as exc:
        await _call("masking_failed", fields)
    assert exc.value.status_code == 422
