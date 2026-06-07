r"""Integration tests for windowed media retention (#338).

Two surfaces:

  1. ``GET /api/v1/notes/{session_id}/audio-replay-url`` — the flag-gated
     audio-replay endpoint. Exercised end-to-end through the ASGI app
     with the DB + ownership boundary mocked (same isolation strategy as
     ``test_note_response_frame_urls.py``). The S3 list is mocked but the
     presign runs for REAL against a ca-central-1 boto3 client (presigning
     is an offline operation), so the assertion that the signed URL is a
     genuine SigV4 presign scoped to the ca-central-1 signing region
     (``.../ca-central-1/s3/aws4_request`` in the credential scope) holds.

  2. Purge-on-approval wiring in ``approve_final_note`` — exercised by
     calling the route coroutine directly with its collaborators patched,
     so we can assert the flag gate + the first-approval-only contract
     without standing up the note-gen / transition machinery.

These run with no LocalStack / Postgres; CI runs the same suite against
the live stack.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

# Env must be set before the app imports load. APP_ENV=local enables the
# dev-token bearer shape `<role>:<user_id>`; the region + creds let the
# real boto3 client presign offline against the ca-central-1 host.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import boto3  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.v1 import notes as notes_module  # noqa: E402
from app.core.audit_events import AuditEventType  # noqa: E402
from app.core.models import SessionModel  # noqa: E402
from app.core.types import (  # noqa: E402
    Note,
    NoteSection,
    SessionState,
    UserRole,
)
from app.modules.config.schema import (  # noqa: E402
    AppConfigSchema,
    FeatureFlagsConfig,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def clinician_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def session_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def auth_headers(clinician_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer CLINICIAN:{clinician_id}"}


def _session(
    session_uuid: uuid.UUID,
    clinician_id: uuid.UUID,
    state: SessionState,
) -> SessionModel:
    return SessionModel(
        id=session_uuid,
        clinician_id=clinician_id,
        specialty="orthopedic_surgery",
        state=state,
    )


def _config(*, retention: bool) -> AppConfigSchema:
    return AppConfigSchema(
        feature_flags=FeatureFlagsConfig(media_review_retention_enabled=retention)
    )


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI in-process client; DB dependency yields a MagicMock (never
    queried — get_session is patched at the helpers boundary)."""
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
    """Replace the AuditLogService singleton with an AsyncMock so audit
    writes never touch DynamoDB."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


def _real_s3_with_audio(session_uuid: uuid.UUID) -> MagicMock:
    """A real ca-central-1 boto3 S3 client (for genuine offline presigning)
    whose ``list_objects_v2`` is stubbed to report one audio object."""
    client = boto3.client(
        "s3",
        region_name="ca-central-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    client.list_objects_v2 = MagicMock(
        return_value={"Contents": [{"Key": f"audio/{session_uuid}/clip.wav"}]}
    )
    return client


# ── GET /audio-replay-url ────────────────────────────────────────────────────


async def test_audio_replay_url_flag_on_returns_signed_cacentral_url(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """Flag ON + AWAITING_REVIEW → 200 with a signed s3.ca-central-1 URL,
    and an EVIDENCE_REPLAYED audit row carrying only actor_id /
    evidence_kind / ttl_seconds."""
    session = _session(session_uuid, clinician_id, SessionState.AWAITING_REVIEW)
    real_s3 = _real_s3_with_audio(session_uuid)

    with (
        patch(
            "app.api.v1._helpers.get_session",
            AsyncMock(return_value=session),
        ),
        patch.object(notes_module, "get_config", return_value=_config(retention=True)),
        patch.object(notes_module, "get_s3_client", return_value=real_s3),
        patch("app.core.s3.get_s3_client", return_value=real_s3),
    ):
        resp = await app_client.get(
            f"/api/v1/notes/{session_uuid}/audio-replay-url",
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["expires_in"] == 3600
    assert payload["audio_url"] is not None
    # Genuine SigV4 presign: the credential scope pins the ca-central-1
    # signing region (`.../ca-central-1/s3/aws4_request`) and the URL is
    # signed + scoped to the retained audio object.
    url = payload["audio_url"]
    assert url.startswith("https://")
    assert "ca-central-1" in url
    assert "X-Amz-Signature=" in url
    assert f"audio/{session_uuid}/clip.wav" in url

    # EVIDENCE_REPLAYED emitted with exactly the PHI-free kwargs.
    replay_calls = [
        c
        for c in mock_audit.write_event.await_args_list
        if c.kwargs.get("event_type") == AuditEventType.EVIDENCE_REPLAYED
    ]
    assert len(replay_calls) == 1
    kwargs = replay_calls[0].kwargs
    assert kwargs["actor_id"] == str(clinician_id)
    assert kwargs["evidence_kind"] == "audio"
    assert kwargs["ttl_seconds"] == 3600
    # No S3 key / URL ever lands in the audit row.
    assert "s3_key" not in kwargs
    assert "audio_url" not in kwargs


async def test_audio_replay_url_flag_off_returns_403(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """Flag OFF → 403 before any session lookup or audit write."""
    with patch.object(
        notes_module, "get_config", return_value=_config(retention=False)
    ):
        resp = await app_client.get(
            f"/api/v1/notes/{session_uuid}/audio-replay-url",
            headers=auth_headers,
        )

    assert resp.status_code == 403, resp.text
    mock_audit.write_event.assert_not_awaited()


async def test_audio_replay_url_exported_state_returns_409(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """Flag ON but session EXPORTED (audio no longer retained) → 409."""
    session = _session(session_uuid, clinician_id, SessionState.EXPORTED)
    with (
        patch(
            "app.api.v1._helpers.get_session",
            AsyncMock(return_value=session),
        ),
        patch.object(notes_module, "get_config", return_value=_config(retention=True)),
    ):
        resp = await app_client.get(
            f"/api/v1/notes/{session_uuid}/audio-replay-url",
            headers=auth_headers,
        )

    assert resp.status_code == 409, resp.text


async def test_audio_replay_url_no_audio_degrades_to_null(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    clinician_id: uuid.UUID,
    mock_audit: MagicMock,
) -> None:
    """Flag ON + valid state but no audio object (already purged) → 200
    with audio_url=null (graceful degradation), EVIDENCE_REPLAYED still
    written."""
    session = _session(session_uuid, clinician_id, SessionState.REVIEW_COMPLETE)
    empty_s3 = MagicMock()
    empty_s3.list_objects_v2 = MagicMock(return_value={})

    with (
        patch(
            "app.api.v1._helpers.get_session",
            AsyncMock(return_value=session),
        ),
        patch.object(notes_module, "get_config", return_value=_config(retention=True)),
        patch.object(notes_module, "get_s3_client", return_value=empty_s3),
    ):
        resp = await app_client.get(
            f"/api/v1/notes/{session_uuid}/audio-replay-url",
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["audio_url"] is None
    assert resp.json()["expires_in"] == 3600


# ── Purge-on-approval wiring ─────────────────────────────────────────────────


def _approvable_note(session_uuid: uuid.UUID) -> Note:
    """A conflict-free, approvable note."""
    return Note(
        session_id=str(session_uuid),
        stage=2,
        version=3,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.83,
        sections=[NoteSection(id="plan", status="populated", claims=[])],
    )


async def _call_approve(
    session: SessionModel,
    note: Note,
    *,
    retention: bool,
    already_approved: bool,
) -> tuple[object, AsyncMock]:
    """Invoke approve_final_note with collaborators patched; return the
    response + the purge mock."""
    user = MagicMock(user_id=session.clinician_id, role=UserRole.CLINICIAN)
    purge_mock = AsyncMock()
    with (
        patch.object(
            notes_module,
            "get_owned_session_or_404",
            AsyncMock(return_value=session),
        ),
        patch.object(notes_module, "get_latest_note", AsyncMock(return_value=note)),
        patch.object(
            notes_module,
            "is_note_approved",
            AsyncMock(return_value=already_approved),
        ),
        patch.object(notes_module, "approve_note", AsyncMock(return_value=note)),
        patch.object(notes_module, "transition_session", AsyncMock()),
        patch.object(notes_module, "write_audit", AsyncMock()),
        patch.object(
            notes_module, "get_config", return_value=_config(retention=retention)
        ),
        patch.object(notes_module, "purge_session_media", new=purge_mock),
    ):
        resp = await notes_module.approve_final_note(
            session_id=session.id, user=user, db=MagicMock()
        )
    return resp, purge_mock


@pytest.mark.asyncio
async def test_approve_purges_on_first_approval_when_flag_on(
    session_uuid: uuid.UUID, clinician_id: uuid.UUID
) -> None:
    session = _session(session_uuid, clinician_id, SessionState.PROCESSING_STAGE2)
    note = _approvable_note(session_uuid)
    resp, purge_mock = await _call_approve(
        session, note, retention=True, already_approved=False
    )
    assert resp.approved is True
    purge_mock.assert_awaited_once_with(str(session_uuid))


@pytest.mark.asyncio
async def test_approve_does_not_purge_when_flag_off(
    session_uuid: uuid.UUID, clinician_id: uuid.UUID
) -> None:
    session = _session(session_uuid, clinician_id, SessionState.PROCESSING_STAGE2)
    note = _approvable_note(session_uuid)
    resp, purge_mock = await _call_approve(
        session, note, retention=False, already_approved=False
    )
    assert resp.approved is True
    purge_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reapproval_does_not_repurge(
    session_uuid: uuid.UUID, clinician_id: uuid.UUID
) -> None:
    """Already-approved + REVIEW_COMPLETE returns early BEFORE the purge
    block, so re-approval never re-purges even with the flag on."""
    session = _session(session_uuid, clinician_id, SessionState.REVIEW_COMPLETE)
    note = _approvable_note(session_uuid)
    resp, purge_mock = await _call_approve(
        session, note, retention=True, already_approved=True
    )
    assert resp.approved is True
    assert resp.message == "Note was already approved."
    purge_mock.assert_not_awaited()
