r"""Integration tests for POST /api/v1/clips/{session_id} (P1-3).

Covers the security model line-for-line against the frames endpoint:
fail-closed masking gate, owner assertion, role gate, content-type
validation, audit emission, and PHI log scan. The endpoint itself
lives in `app/api/v1/clips.py`; this suite is the AC harness from the
P1-3 plan (docs/plans/p1-3-clips-endpoint.md).

Test isolation strategy
-----------------------
Unlike the e2e suite (which requires a live Postgres), these tests
mock the DB session helpers directly so they run on every developer
push without infrastructure dependencies. The auth dev-token shape
(``<role>:<user_id>``) gives a real CurrentUser; `get_session` is
patched at the helpers boundary to return a stub SessionModel.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

# Set env before app import — APP_ENV=local enables the dev-token
# bearer shape `<role>:<user_id>` parsed by `_parse_dev_token`.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.models import SessionModel  # noqa: E402
from app.core.types import SessionState  # noqa: E402

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def clinician_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def session_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def auth_headers(clinician_id: uuid.UUID) -> dict[str, str]:
    """Dev-token bearer for a CLINICIAN role.

    `APP_ENV=local` makes `_parse_dev_token` parse `<role>:<user_id>`
    so the same UUID flows through `CurrentUser.user_id` and back into
    the owner assertion.
    """
    return {"Authorization": f"Bearer CLINICIAN:{clinician_id}"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer ADMIN:{uuid.uuid4()}"}


@pytest.fixture
def session_owned_by_clinician(
    session_uuid: uuid.UUID, clinician_id: uuid.UUID
) -> SessionModel:
    """A SessionModel stub matching the clinician identity.

    `get_owned_session_or_404` reads `clinician_id` + `state`; nothing
    else is required for the upload path.
    """
    return SessionModel(
        id=session_uuid,
        clinician_id=clinician_id,
        specialty="orthopedic_surgery",
        state=SessionState.RECORDING,
    )


@pytest.fixture
def session_owned_by_other(session_uuid: uuid.UUID) -> SessionModel:
    """A SessionModel stub owned by a different clinician.

    Used to verify the owner assertion blocks cross-clinician posts.
    """
    return SessionModel(
        id=session_uuid,
        clinician_id=uuid.uuid4(),  # different from auth_headers's id
        specialty="orthopedic_surgery",
        state=SessionState.RECORDING,
    )


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI in-process client; no DB connection needed.

    The DB dependency yields a MagicMock that's never actually queried —
    `get_session` is patched at the helpers boundary so the
    transactional `get_db` path is bypassed.
    """
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
    writes never touch DynamoDB and tests can assert against
    `mock_audit.write_event`."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


@pytest.fixture
def mock_s3():
    """Patch the shared S3 client factory with a MagicMock and yield it
    so tests can assert on `put_object` calls."""
    client = MagicMock()
    client.put_object = MagicMock(return_value={"ETag": "stub"})
    with patch(
        "app.api.v1.clips.get_s3_client", return_value=client
    ):
        yield client


def _multipart_body(
    *,
    masking_confirmed: bool = True,
    timestamp_ms: int = 14500,
    duration_ms: int = 7000,
    trigger_segment_id: str = "seg_001",
    frames_total: int = 210,
    frames_with_faces: int = 210,
    content_type: str = "video/mp4",
    body_bytes: bytes = b"\x00\x00\x00\x18ftypmp42",  # MP4 signature
    source: str | None = None,
) -> tuple[dict, dict]:
    """Build (data, files) for an httpx multipart POST."""
    data = {
        "timestamp_ms": str(timestamp_ms),
        "duration_ms": str(duration_ms),
        "trigger_segment_id": trigger_segment_id,
        "frames_total": str(frames_total),
        "frames_with_faces": str(frames_with_faces),
        "masking_confirmed": str(masking_confirmed).lower(),
    }
    if source is not None:
        data["source"] = source
    files = {"clip": ("clip.mp4", body_bytes, content_type)}
    return data, files


# ── Tests ───────────────────────────────────────────────────────────────────


async def test_happy_path_clip_upload(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """AC-1: masking_confirmed=true → 200, S3 PutObject + audit event fire."""

    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body()
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_id"] == str(session_uuid)
    assert payload["s3_key"].startswith(f"clips/{session_uuid}/")
    assert payload["s3_key"].endswith(".mp4")
    assert payload["evidence_kind"] == "clip"
    assert payload["duration_ms"] == 7000
    assert payload["bytes_uploaded"] > 0
    assert "clip_id" in payload

    # S3 PutObject fired with KMS encryption + correct mime type.
    mock_s3.put_object.assert_called_once()
    call_kwargs = mock_s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "video/mp4"
    assert call_kwargs["ServerSideEncryption"] == "aws:kms"
    assert call_kwargs["Key"].startswith(f"clips/{session_uuid}/")

    # Audit event emitted with the masking metadata.
    mock_audit.write_event.assert_called_once()
    audit_call = mock_audit.write_event.call_args.kwargs
    assert audit_call["event_type"].value == "clip_uploaded"
    assert audit_call["duration_ms"] == 7000
    assert audit_call["trigger_segment_id"] == "seg_001"
    assert audit_call["frames_total"] == 210
    assert audit_call["frames_with_faces"] == 210
    assert audit_call["masking_status"] == "success"


async def test_fail_closed_rejects_unmasked_clip(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """AC-2: masking_confirmed=false → 400, NO S3 write, NO audit event."""

    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body(masking_confirmed=False)
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 400, response.text
    assert "masking_confirmed" in response.json()["detail"]
    # P0-01 fail-closed: no S3 write, no audit event.
    mock_s3.put_object.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_content_type_validation_rejects_jpeg(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """AC-3: image/jpeg content-type → 400, no S3 write, no audit."""

    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body(content_type="image/jpeg")
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 400, response.text
    assert "content type" in response.json()["detail"].lower()
    mock_s3.put_object.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_owner_assertion_blocks_cross_clinician(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_other: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """AC-4: CLINICIAN posting to another clinician's session → 404.

    Per `_helpers.assert_owner`, clinician-to-clinician cross-talk
    surfaces as 404 (not 403) to avoid leaking session existence.
    """
    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_other),
    ):
        data, files = _multipart_body()
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 404, response.text
    mock_s3.put_object.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_missing_required_fields_returns_422(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
) -> None:
    """AC-5: missing required form fields → 422 from FastAPI validation."""

    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        # Drop `trigger_segment_id` from the form payload.
        data = {
            "timestamp_ms": "14500",
            "duration_ms": "7000",
            "frames_total": "210",
            "frames_with_faces": "210",
            "masking_confirmed": "true",
        }
        files = {"clip": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")}
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 422, response.text


async def test_empty_body_returns_400(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """Empty clip body → 400 (no S3 write of an empty object)."""

    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body(body_bytes=b"")
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 400, response.text
    mock_s3.put_object.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_clip_id_is_server_generated_and_unique(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """Two uploads to the same session generate distinct S3 keys.

    The endpoint generates a UUID per upload — replaying the same
    trigger_segment_id doesn't clobber the previous clip.
    """
    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body()
        r1 = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )
        # httpx multipart files are exhausted after one upload — rebuild.
        data, files = _multipart_body()
        r2 = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["clip_id"] != r2.json()["clip_id"]
    assert r1.json()["s3_key"] != r2.json()["s3_key"]


# ── #324 clip cadence floor ───────────────────────────────────────────────


async def test_clip_key_embeds_timestamp(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """#324: the S3 key embeds the zero-padded timestamp_ms prefix so
    Stage 2 can recover each clip's real anchor — clips/{sid}/{ts:09d}_*.mp4."""
    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body(timestamp_ms=14500)
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 200, response.text
    key = response.json()["s3_key"]
    assert key.startswith(f"clips/{session_uuid}/000014500_")
    assert key.endswith(".mp4")
    # The persisted S3 key matches the response key.
    assert mock_s3.put_object.call_args.kwargs["Key"] == key


async def test_source_defaults_to_trigger_in_audit(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """#324: omitting `source` defaults to "trigger" in the CLIP_UPLOADED
    audit (back-compat for older iOS builds)."""
    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body()  # no source field
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 200, response.text
    assert mock_audit.write_event.call_args.kwargs["source"] == "trigger"


async def test_source_cadence_recorded_in_audit(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """#324: source="cadence" is carried into the CLIP_UPLOADED audit."""
    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body(source="cadence")
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 200, response.text
    assert mock_audit.write_event.call_args.kwargs["source"] == "cadence"


async def test_invalid_source_rejected(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """#324: a source outside the {trigger, cadence} Literal → 422."""
    with patch(
        "app.api.v1._helpers.get_session",
        AsyncMock(return_value=session_owned_by_clinician),
    ):
        data, files = _multipart_body(source="bogus")
        response = await app_client.post(
            f"/api/v1/clips/{session_uuid}",
            headers=auth_headers,
            data=data,
            files=files,
        )

    assert response.status_code == 422, response.text
    mock_s3.put_object.assert_not_called()
    mock_audit.write_event.assert_not_called()


# ── PHI scan ────────────────────────────────────────────────────────────────


def _extract_logger_calls(source: str) -> list[str]:
    """Extract `logger.<level>(...)` call expressions from a Python
    source string using ast — comments + docstrings are ignored.
    """
    import ast

    tree = ast.parse(source)
    calls: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            calls.append(ast.unparse(node))
    return calls


def test_no_phi_in_clips_module_log_statements() -> None:
    """AC-9 (partial): the clips.py route never logs full session_id or
    clip body bytes.

    Uses an AST walk to extract every `logger.*(...)` call and check
    each one for forbidden argument patterns. This is precise: comments
    and docstrings (which mention `session_id` plenty) are ignored, but
    any new log line that passes session_id raw trips the assertion.
    """
    import inspect

    from app.api.v1 import clips as clips_module

    source = inspect.getsource(clips_module)
    logger_calls = _extract_logger_calls(source)
    assert logger_calls, "Expected at least one logger.* call in clips.py."

    forbidden_substrings = [
        # Bare session_id (UUID) as positional arg to logger:
        ", session_id,",
        ", session_id)",
        # Body bytes ever passed to logger:
        ", body,",
        ", body)",
        "mp4_bytes",
    ]
    for call_src in logger_calls:
        for needle in forbidden_substrings:
            assert needle not in call_src, (
                f"PHI scan: logger call {call_src!r} carries forbidden "
                f"pattern {needle!r}. Use _session_log_prefix(session_id) "
                "and never pass clip body bytes to a logger."
            )

    # Positive check: at least one logger call truncates session_id via
    # the helper. Guards against a future refactor that drops the
    # truncation entirely.
    assert any(
        "_session_log_prefix(session_id)" in call for call in logger_calls
    ), (
        "Expected at least one clips.py logger call to truncate "
        "session_id via _session_log_prefix — none found."
    )
