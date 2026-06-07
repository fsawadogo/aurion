"""Integration tests for the Visit Type → Context → Template wiring on
POST /sessions (#314, B2).

The real resolution logic is unit-tested in
``tests/unit/test_session_context_template.py``; here we verify the
ROUTE wiring against a mocked DB + service:

  1. ``context_id`` from the body + the resolver's snapshot template_key
     are both forwarded into ``create_session``.
  2. A stale-pin coercion emits the count-only
     ``SESSION_TEMPLATE_KEY_COERCED`` audit event (no kwargs / no PHI).
  3. The old-client path (no ``context_id``) forwards None/None and emits
     no coercion event.

These mock ``resolve_context_template_key`` and ``create_session`` via
the route's import site, the same pattern test_session_mode_override.py
uses, so they run without Postgres.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ────────────────────────────────────────────────────────────────


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


def _make_session_row(clinician_id: uuid.UUID):
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
    row.created_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    return row


def _event_values(mock_audit: MagicMock) -> list[str]:
    return [
        c.kwargs["event_type"].value
        for c in mock_audit.write_event.call_args_list
    ]


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_id_and_resolved_template_forwarded(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """A context that maps to a built-in template: the body's context_id
    and the resolver's snapshot key both reach create_session."""
    stub_row = _make_session_row(clinician_id)
    with (
        patch(
            "app.api.v1.sessions.resolve_context_template_key",
            AsyncMock(return_value=("musculoskeletal", False)),
        ) as resolve_mock,
        patch(
            "app.api.v1.sessions.create_session",
            AsyncMock(return_value=stub_row),
        ) as create_mock,
    ):
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "specialty": "orthopedic_surgery",
                "consultation_type": "new_patient",
                "context_id": "ctx_aaaaaaaa",
            },
        )

    assert response.status_code == 201, response.text

    resolve_kwargs = resolve_mock.call_args.kwargs
    assert resolve_kwargs["consultation_type"] == "new_patient"
    assert resolve_kwargs["context_id"] == "ctx_aaaaaaaa"
    assert resolve_kwargs["clinician_id"] == clinician_id

    create_kwargs = create_mock.call_args.kwargs
    assert create_kwargs["context_id"] == "ctx_aaaaaaaa"
    assert create_kwargs["template_key"] == "musculoskeletal"

    # No coercion → no coercion audit row.
    assert "session_template_key_coerced" not in _event_values(mock_audit)


@pytest.mark.asyncio
async def test_stale_pin_emits_count_only_coercion_audit(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """Resolver coerced a stale pin → template_key None on the row AND a
    count-only SESSION_TEMPLATE_KEY_COERCED event with no PHI kwargs."""
    stub_row = _make_session_row(clinician_id)
    with (
        patch(
            "app.api.v1.sessions.resolve_context_template_key",
            AsyncMock(return_value=(None, True)),
        ),
        patch(
            "app.api.v1.sessions.create_session",
            AsyncMock(return_value=stub_row),
        ) as create_mock,
    ):
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "specialty": "orthopedic_surgery",
                "consultation_type": "new_patient",
                "context_id": "ctx_eeeeeeee",
            },
        )

    assert response.status_code == 201, response.text

    # The context id is still persisted; the template snapshot fell back.
    create_kwargs = create_mock.call_args.kwargs
    assert create_kwargs["context_id"] == "ctx_eeeeeeee"
    assert create_kwargs["template_key"] is None

    events = _event_values(mock_audit)
    assert "session_created" in events
    assert "session_template_key_coerced" in events

    coerced_call = next(
        c
        for c in mock_audit.write_event.call_args_list
        if c.kwargs["event_type"].value == "session_template_key_coerced"
    )
    # Count-only: the row's existence is the signal. No context id /
    # template name / label may ride along.
    forbidden = {"context_id", "template_key", "label", "consultation_type"}
    assert forbidden.isdisjoint(coerced_call.kwargs.keys())


@pytest.mark.asyncio
async def test_old_client_no_context_id_forwards_none(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """Old clients omit context_id: resolver is called with None, both
    columns forward None, and no coercion event fires."""
    stub_row = _make_session_row(clinician_id)
    with (
        patch(
            "app.api.v1.sessions.resolve_context_template_key",
            AsyncMock(return_value=(None, False)),
        ) as resolve_mock,
        patch(
            "app.api.v1.sessions.create_session",
            AsyncMock(return_value=stub_row),
        ) as create_mock,
    ):
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={"specialty": "orthopedic_surgery"},
        )

    assert response.status_code == 201, response.text

    assert resolve_mock.call_args.kwargs["context_id"] is None
    create_kwargs = create_mock.call_args.kwargs
    assert create_kwargs["context_id"] is None
    assert create_kwargs["template_key"] is None

    assert "session_template_key_coerced" not in _event_values(mock_audit)
