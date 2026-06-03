"""Integration tests for the per-session visual_evidence_mode override
(P1-7).

Covers the full POST /sessions surface that this PR added:

  1. happy-path round-trip — override stored + audit row emitted
  2. invalid mode enum → 422
  3. unknown override key → 422 (extra='forbid' on the schema)
  4. flag-disabled gate → 400 with documented error string
  5. PHI check — no transcript content / patient identifiers in the
     audit kwargs (the kwargs whitelist enforces this at write time,
     but we double-check at the route layer too)

These tests mock the DB session via the FastAPI dependency override
the rest of the integration suite uses (see test_clips_endpoint.py)
so they run on every developer push without infrastructure.
"""

from __future__ import annotations

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

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def clinician_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def auth_headers(clinician_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer CLINICIAN:{clinician_id}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI client; mocks the DB dependency and the session.create_session
    call so the route under test is exercised end-to-end without a
    Postgres connection."""
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
    """AsyncMock-backed audit service; tests assert via
    `mock_audit.write_event.call_args_list`."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


def _make_session_row(
    clinician_id: uuid.UUID,
    provider_overrides_json: str | None = None,
):
    """Build a SessionModel stand-in matching what the service returns
    after create_session. We don't go through the ORM here — the route
    only reads attributes off the returned object, never persists."""
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
    row.provider_overrides = provider_overrides_json
    row.created_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    return row


@pytest.fixture
def flag_enabled(monkeypatch):
    """Feature-flag fixture — ON. Patches get_config at the route's
    import site so the route reads our stub instead of fetching real
    AppConfig.

    Important: also patches `app.modules.session.service.get_config`
    in case any future service-layer read of the same flag lands. Keeps
    the test stable against that refactor.
    """
    from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig

    flags = FeatureFlagsConfig(per_session_visual_evidence_mode_override=True)
    cfg = AppConfigSchema(feature_flags=flags)
    monkeypatch.setattr("app.api.v1.sessions.get_config", lambda: cfg)
    return cfg


@pytest.fixture
def flag_disabled(monkeypatch):
    """Feature-flag fixture — OFF."""
    from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig

    flags = FeatureFlagsConfig(per_session_visual_evidence_mode_override=False)
    cfg = AppConfigSchema(feature_flags=flags)
    monkeypatch.setattr("app.api.v1.sessions.get_config", lambda: cfg)
    return cfg


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_session_with_visual_evidence_mode_override_roundtrips(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
    flag_enabled,
) -> None:
    """AC-1: 201 + override echoes back on the response body."""
    # The service writes the JSON-encoded dict to the row; we stub it
    # to return a row that mirrors what _to_response will receive.
    stub_row = _make_session_row(
        clinician_id,
        provider_overrides_json='{"visual_evidence_mode": "clips_only"}',
    )
    with patch(
        "app.api.v1.sessions.create_session",
        AsyncMock(return_value=stub_row),
    ) as _create_mock:
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "specialty": "orthopedic_surgery",
                "provider_overrides": {"visual_evidence_mode": "clips_only"},
            },
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    # Response surfaces the override structured (not as a JSON string).
    assert payload["provider_overrides"] == {
        "visual_evidence_mode": "clips_only"
    }
    # Service was called with the validated dict (mode='json' on the
    # Pydantic model dumps the enum as its string value).
    call_kwargs = _create_mock.call_args.kwargs
    assert call_kwargs["provider_overrides"] == {
        "visual_evidence_mode": "clips_only"
    }


@pytest.mark.asyncio
async def test_invalid_visual_evidence_mode_rejected(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    flag_enabled,
) -> None:
    """AC-2: invalid enum value → 422 at Pydantic validation."""
    response = await app_client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "specialty": "orthopedic_surgery",
            "provider_overrides": {"visual_evidence_mode": "INVALID"},
        },
    )
    assert response.status_code == 422, response.text
    # Pydantic error mentions the bad value somewhere in the detail
    # payload — exact path varies by Pydantic version, so we check
    # against the rendered string.
    body = response.text
    assert "visual_evidence_mode" in body or "INVALID" in body.lower()


@pytest.mark.asyncio
async def test_unknown_override_key_rejected(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    flag_enabled,
) -> None:
    """AC-3: unknown keys rejected at the API boundary (extra='forbid')."""
    response = await app_client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "specialty": "orthopedic_surgery",
            "provider_overrides": {"foo": "bar"},
        },
    )
    assert response.status_code == 422, response.text
    assert "foo" in response.text or "extra" in response.text.lower()


@pytest.mark.asyncio
async def test_override_disabled_returns_400(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    flag_disabled,
) -> None:
    """AC-4: flag off + override in body → 400 with documented detail."""
    response = await app_client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "specialty": "orthopedic_surgery",
            "provider_overrides": {"visual_evidence_mode": "clips_only"},
        },
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "visual_evidence_mode" in detail
    assert "disabled" in detail


@pytest.mark.asyncio
async def test_override_disabled_does_not_block_other_overrides(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    flag_disabled,
    mock_audit: MagicMock,
) -> None:
    """The flag gates ONLY `visual_evidence_mode`. Other overrides like
    a per-session note_generation provider remain accepted while the
    flag is off."""
    stub_row = _make_session_row(
        clinician_id,
        provider_overrides_json='{"note_generation": "anthropic"}',
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
                "provider_overrides": {"note_generation": "anthropic"},
            },
        )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_override_set_emits_audit_event(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
    flag_enabled,
) -> None:
    """AC-5: VISUAL_EVIDENCE_MODE_OVERRIDE_SET fires with the right kwargs."""
    stub_row = _make_session_row(
        clinician_id,
        provider_overrides_json='{"visual_evidence_mode": "hybrid"}',
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
                "provider_overrides": {"visual_evidence_mode": "hybrid"},
            },
        )
    assert response.status_code == 201, response.text

    # Two audit events total: SESSION_CREATED + VISUAL_EVIDENCE_MODE_OVERRIDE_SET.
    audit_calls = mock_audit.write_event.call_args_list
    event_types = [c.kwargs["event_type"].value for c in audit_calls]
    assert "session_created" in event_types
    assert "visual_evidence_mode_override_set" in event_types

    # The override event carries the documented kwargs and nothing PHI.
    override_call = next(
        c for c in audit_calls
        if c.kwargs["event_type"].value == "visual_evidence_mode_override_set"
    )
    assert override_call.kwargs["mode"] == "hybrid"
    assert override_call.kwargs["actor_id"] == str(clinician_id)
    assert override_call.kwargs["actor_role"] == "CLINICIAN"
    # Sanity: no transcript/PHI keys leaked into the kwargs.
    forbidden_keys = {"transcript", "encounter_context", "patient", "external_reference_id"}
    assert forbidden_keys.isdisjoint(override_call.kwargs.keys())


@pytest.mark.asyncio
async def test_no_audit_emitted_when_override_absent(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
    flag_enabled,
) -> None:
    """Sessions created without a visual_evidence_mode override must NOT
    emit the override event — the eval-team's Phase 2 query relies on
    the event firing only when the eval team actually flipped a session."""
    stub_row = _make_session_row(clinician_id, provider_overrides_json=None)
    with patch(
        "app.api.v1.sessions.create_session",
        AsyncMock(return_value=stub_row),
    ):
        response = await app_client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={"specialty": "orthopedic_surgery"},
        )
    assert response.status_code == 201, response.text

    event_types = [
        c.kwargs["event_type"].value
        for c in mock_audit.write_event.call_args_list
    ]
    assert "session_created" in event_types
    assert "visual_evidence_mode_override_set" not in event_types
