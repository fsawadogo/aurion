"""Integration tests for encounter participants on POST /sessions (#275).

Exercises the route surface end-to-end without Postgres (mocked DB
dependency + patched ``create_session``), mirroring
``test_session_mode_override.py``:

  1. happy-path round-trip — named + anonymous chips accepted (201) and
     surfaced back on the response body (B1 + B2).
  2. ``adhoc_role`` carrying a name → 422 (B1 validator).
  3. ``source="profile"`` with no name → 422 (B1 validator).
  4. PHI guard — the SESSION_CREATED audit kwargs carry only
     clinician_id + specialty, never a participant name.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest.fixture
def clinician_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def auth_headers(clinician_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer CLINICIAN:{clinician_id}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    from app.core.database import get_db
    from app.main import app

    async def _yield_mock_db() -> AsyncGenerator[MagicMock, None]:
        yield MagicMock()

    app.dependency_overrides[get_db] = _yield_mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://aurion.test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def mock_audit(monkeypatch):
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


def _make_session_row(
    clinician_id: uuid.UUID,
    participants_json: str | None = None,
):
    from datetime import datetime, timezone

    from app.core.types import SessionState

    row = MagicMock()
    row.id = uuid.uuid4()
    row.clinician_id = clinician_id
    row.specialty = "orthopedic_surgery"
    row.state = SessionState.CONSENT_PENDING
    row.encounter_type = "doctor_patient"
    row.capture_mode = "multimodal"
    row.external_reference_id_encrypted = None
    row.provider_overrides = None
    row.participants_json = participants_json
    row.created_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    return row


@pytest.mark.asyncio
async def test_create_session_with_participants_roundtrips(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """B1 + B2: named + anonymous chips accepted and surfaced back."""
    persisted = [
        {"name": "Dr. Lee", "role": "physician",
         "source": "profile", "is_persistent": True},
        {"name": None, "role": "nurse",
         "source": "adhoc_role", "is_persistent": False},
    ]
    stub_row = _make_session_row(clinician_id, json.dumps(persisted))
    with patch(
        "app.api.v1.sessions.create_session",
        AsyncMock(return_value=stub_row),
    ) as create_mock:
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "specialty": "orthopedic_surgery",
                "participants": [
                    {"name": "Dr. Lee", "role": "physician",
                     "source": "profile"},
                    {"role": "nurse", "source": "adhoc_role"},
                ],
            },
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["participants"] == persisted
    assert payload["encounter_type"] == "doctor_patient"

    # The service receives normalized participant dicts: is_persistent
    # derived from source, anonymous chip name → None.
    sent = create_mock.await_args.kwargs["participants"]
    assert sent == [
        {"name": "Dr. Lee", "role": "physician",
         "source": "profile", "is_persistent": True},
        {"name": None, "role": "nurse",
         "source": "adhoc_role", "is_persistent": False},
    ]


@pytest.mark.asyncio
async def test_adhoc_role_with_name_rejected_422(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    mock_audit: MagicMock,
) -> None:
    response = await app_client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "specialty": "orthopedic_surgery",
            "participants": [
                {"name": "Sarah Chen", "role": "nurse", "source": "adhoc_role"},
            ],
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_profile_source_without_name_rejected_422(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    mock_audit: MagicMock,
) -> None:
    response = await app_client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "specialty": "orthopedic_surgery",
            "participants": [
                {"role": "resident", "source": "profile"},
            ],
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_session_created_audit_carries_no_participant_names(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """PHI guard: SESSION_CREATED kwargs are clinician_id + specialty
    only — a participant name must never reach the immutable audit log."""
    from app.core.audit_events import AuditEventType

    stub_row = _make_session_row(
        clinician_id,
        json.dumps([
            {"name": "Sarah Chen", "role": "nurse",
             "source": "adhoc_named", "is_persistent": False},
        ]),
    )
    with patch(
        "app.api.v1.sessions.create_session",
        AsyncMock(return_value=stub_row),
    ):
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "specialty": "orthopedic_surgery",
                "participants": [
                    {"name": "Sarah Chen", "role": "nurse",
                     "source": "adhoc_named"},
                ],
            },
        )
    assert response.status_code == 201, response.text

    created_calls = [
        c for c in mock_audit.write_event.call_args_list
        if c.kwargs.get("event_type") == AuditEventType.SESSION_CREATED
    ]
    assert len(created_calls) == 1
    payload_str = repr(created_calls[0].kwargs)
    assert "Sarah" not in payload_str
    assert "Chen" not in payload_str
