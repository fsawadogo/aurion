"""Integration tests for POST /api/v1/admin/probe/vision-clip
(P1-FU-GEMINI-PROBE).

Covers the AC harness from `docs/plans/p1-fu-gemini-probe.md`:
admin-only gating, content-type + size validation, registry-resolved
provider call with timer, structured success + failure diagnostics,
API-key scrub on every error_message, no session persistence, S3
temp object always deleted, audit row on every call, bundled fixture
validity.

Test isolation strategy
-----------------------
The route depends on the FastAPI app + auth helper + the registry +
S3 client + audit service. We mock at the smallest possible surface:

  * `get_vision_provider_for_kind` — returns a stub provider whose
    `caption_clip` is an `AsyncMock` we can configure per-test.
  * `get_s3_client` — `MagicMock` so `put_object` / `delete_object`
    can be asserted without LocalStack.
  * `_service` on the audit module — `MagicMock` so `write_event`
    is asserted in-memory.
  * `get_db` — yields a `MagicMock`; the probe doesn't touch DB.

The dev-token bearer shape `<role>:<user_id>` gives a real
CurrentUser without Cognito.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

# Env BEFORE the FastAPI app import — `APP_ENV=local` makes the auth
# layer parse `<role>:<user_id>` dev tokens rather than Cognito JWTs.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.types import (  # noqa: E402
    FrameCaption,
    ProviderError,
)
from app.modules.providers.vision.openai import _MODEL as _OPENAI_MODEL  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def fixture_clip_bytes() -> bytes:
    """The bundled probe MP4 — read once per test, returned as bytes.

    This is the same file an operator would `curl -F clip=@…` upload
    against the local server.
    """
    path = os.path.join(
        os.path.dirname(__file__), "..", "fixtures", "probe_clip.mp4"
    )
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer ADMIN:{uuid.uuid4()}"}


@pytest.fixture
def clinician_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer CLINICIAN:{uuid.uuid4()}"}


@pytest.fixture
def eval_team_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer EVAL_TEAM:{uuid.uuid4()}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI in-process client; no DB connection required.

    The DB dependency yields a `MagicMock` that is never queried —
    the probe doesn't touch the DB so this exists only to keep
    FastAPI's dependency graph happy.
    """
    from app.core.database import get_db
    from app.main import app

    db_mock = MagicMock()

    async def _yield_mock_db() -> AsyncGenerator[MagicMock, None]:
        yield db_mock

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


@pytest.fixture
def mock_s3():
    """Patch the shared S3 client factory inside the probe module so
    `put_object` / `delete_object` calls can be asserted."""
    client = MagicMock()
    client.put_object = MagicMock(return_value={"ETag": "stub"})
    client.delete_object = MagicMock(return_value={})
    with patch("app.api.v1.admin.probe.get_s3_client", return_value=client):
        yield client


@pytest.fixture
def mock_provider_call():
    """Patch the registry's clip-provider resolution so each test can
    configure the stub provider's `caption_clip` outcome.

    Returns the `AsyncMock` for the `caption_clip` method so tests can
    use `.return_value=` / `.side_effect=`.
    """
    stub_provider = MagicMock()
    caption_clip_mock = AsyncMock()
    stub_provider.caption_clip = caption_clip_mock

    def _resolve(kind: str, override=None):
        return stub_provider

    with patch(
        "app.api.v1.admin.probe.get_registry"
    ) as mock_get_registry:
        registry = MagicMock()
        registry.get_vision_provider_for_kind = MagicMock(side_effect=_resolve)
        mock_get_registry.return_value = registry
        yield caption_clip_mock


def _multipart(
    *,
    body_bytes: bytes,
    content_type: str = "video/mp4",
    provider_override: str | None = None,
) -> tuple[dict, dict, dict]:
    """Build (data, files, params) for an httpx multipart POST to the probe.

    P1-FU-FFMPEG: `provider_override` is now a QUERY-STRING parameter
    on the endpoint. Was `Form()` and silently ignored query-string
    values, which is the natural shape for diagnostic curl/Postman
    invocations. The `params` dict surfaces as `?provider_override=…`.
    """
    data: dict = {}
    params: dict = {}
    if provider_override is not None:
        params["provider_override"] = provider_override
    files = {"clip": ("probe_clip.mp4", body_bytes, content_type)}
    return data, files, params


def _valid_frame_caption(provider: str = "gemini") -> FrameCaption:
    """A FrameCaption with the clip-shape fields populated.

    Matches what `caption_clip` returns end-to-end: `evidence_kind=
    "clip"`, `duration_ms` set, `degraded_to_frame=False`.
    """
    return FrameCaption(
        frame_id="probe_seg_test_clip",
        session_id="00000000-0000-0000-0000-000000000000",
        timestamp_ms=1000,
        audio_anchor_id="probe_seg_test",
        provider_used=provider,
        visual_description=(
            "A solid blue test pattern with no clinical content."
        ),
        confidence="low",
        confidence_reason="No clinically relevant content visible.",
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
        evidence_kind="clip",
        duration_ms=2000,
        degraded_to_frame=False,
    )


# ── AC-1, AC-2, AC-12 — happy path ────────────────────────────────────────


async def test_probe_happy_path_returns_caption(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-1: configured provider's `caption_clip` returns a valid
    FrameCaption → 200, `success=true`, `caption.visual_description`
    populated."""
    mock_provider_call.return_value = _valid_frame_caption()

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert payload["caption"] is not None
    assert (
        payload["caption"]["visual_description"]
        == "A solid blue test pattern with no clinical content."
    )
    assert payload["caption"]["evidence_kind"] == "clip"
    # Provider resolution defaults to AppConfig's vision_clip
    # (Gemini in the schema default).
    assert payload["provider_used"] in {"gemini", "openai", "anthropic"}
    # Model id is populated for known providers.
    assert payload["model_id"]
    # Clip metadata echoes the upload shape.
    assert payload["clip_metadata"]["size_bytes"] == len(fixture_clip_bytes)
    assert payload["clip_metadata"]["content_type"] == "video/mp4"


async def test_probe_latency_is_recorded(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-2: latency_ms is non-negative and brackets the provider call.

    The provider mock sleeps for ~30 ms; the wall-clock around the
    call must be at least that.
    """

    async def _slow_caption(clip, anchor):
        await asyncio.sleep(0.03)
        return _valid_frame_caption()

    mock_provider_call.side_effect = _slow_caption

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert payload["latency_ms"] >= 30


async def test_probe_writes_audit_event_on_success(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-12 (success branch): `vision_clip_probed` event fires with
    `{provider, success=true, latency_ms}` on a successful probe."""
    mock_provider_call.return_value = _valid_frame_caption()

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200
    mock_audit.write_event.assert_called_once()
    audit_call = mock_audit.write_event.call_args.kwargs
    assert audit_call["event_type"].value == "vision_clip_probed"
    assert audit_call["success"] is True
    assert audit_call["latency_ms"] >= 0
    assert audit_call["provider"]
    # error_type omitted on success.
    assert "error_type" not in audit_call


# ── AC-3 — ProviderError handled as diagnostic ────────────────────────────


async def test_probe_provider_error_returns_diagnostic(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-3: provider raises ProviderError → 200 with
    `success=false`, `error_type='ProviderError'`, sanitized message."""
    mock_provider_call.side_effect = ProviderError("gemini", "auth failed")

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_type"] == "ProviderError"
    assert "auth failed" in payload["error_message"]
    assert payload["caption"] is None


async def test_probe_writes_audit_event_on_failure(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-12 (failure branch): `vision_clip_probed` event fires with
    `{provider, success=false, latency_ms, error_type}`."""
    mock_provider_call.side_effect = ProviderError("gemini", "auth failed")

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200
    mock_audit.write_event.assert_called_once()
    audit_call = mock_audit.write_event.call_args.kwargs
    assert audit_call["event_type"].value == "vision_clip_probed"
    assert audit_call["success"] is False
    assert audit_call["error_type"] == "ProviderError"
    assert audit_call["latency_ms"] >= 0


# ── AC-4 — timeout handled as diagnostic ──────────────────────────────────


async def test_probe_timeout_returns_diagnostic(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-4: provider call times out → 200 with
    `success=false`, `error_type='TimeoutError'`."""
    mock_provider_call.side_effect = asyncio.TimeoutError()

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_type"] == "TimeoutError"
    assert payload["caption"] is None


# ── AC-5, AC-6, AC-7, AC-8 — input validation + role gate ─────────────────


async def test_probe_blocked_for_clinician_role(
    app_client: AsyncClient,
    clinician_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-5: CLINICIAN token → 403, no S3 write, no provider call,
    no audit row."""
    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=clinician_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 403, response.text
    mock_s3.put_object.assert_not_called()
    mock_provider_call.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_probe_blocked_for_eval_team_role(
    app_client: AsyncClient,
    eval_team_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-5 (extended): EVAL_TEAM token → 403 (probe is ADMIN-only)."""
    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=eval_team_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 403, response.text


async def test_probe_missing_clip_returns_422(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-6: missing `clip` form part → 422 from FastAPI validation."""
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
    )
    assert response.status_code == 422, response.text
    mock_provider_call.assert_not_called()


async def test_probe_rejects_non_mp4_content_type(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-7: image/jpeg content-type → 400, no provider call."""
    data, files, params = _multipart(
        body_bytes=fixture_clip_bytes, content_type="image/jpeg"
    )
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )
    assert response.status_code == 400, response.text
    assert "content type" in response.json()["detail"].lower()
    mock_s3.put_object.assert_not_called()
    mock_provider_call.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_probe_rejects_oversized_clip(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-8: body > 5 MB cap → 400, no provider call."""
    # 5 MB + 1 byte of zeros, still video/mp4 content-type to verify
    # the size check runs AFTER the content-type check.
    oversized = b"\x00" * (5 * 1024 * 1024 + 1)
    data, files, params = _multipart(body_bytes=oversized)

    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 400, response.text
    assert "too large" in response.json()["detail"].lower()
    mock_s3.put_object.assert_not_called()
    mock_provider_call.assert_not_called()
    mock_audit.write_event.assert_not_called()


async def test_probe_rejects_empty_body(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """Empty body → 400 (no S3 write of an empty probe)."""
    data, files, params = _multipart(body_bytes=b"")
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )
    assert response.status_code == 400, response.text
    mock_provider_call.assert_not_called()


# ── AC-9 — PHI scan ───────────────────────────────────────────────────────


def _extract_logger_calls(source: str) -> list[str]:
    """Extract every `logger.<level>(...)` call expression from a
    Python source string using `ast` — comments + docstrings are
    ignored."""
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


def test_no_phi_in_probe_module_log_statements() -> None:
    """AC-9: the probe module's `logger.*` calls never log the clip
    body, never log an API key, never log a raw exception object that
    might carry a key.

    AST walk — picks up only real call expressions, not the comments
    that document the secret-scrub strategy.
    """
    import inspect

    from app.api.v1.admin import probe as probe_module

    source = inspect.getsource(probe_module)
    logger_calls = _extract_logger_calls(source)
    assert logger_calls, "Expected at least one logger.* call in probe.py."

    forbidden_substrings = [
        # The raw body bytes must never be logged.
        ", body,",
        ", body)",
        "mp4_bytes",
        # Raw exception bodies (we always scrub first).
        ", exc,",
        ", exc)",
        ", cleanup_exc,",
        ", cleanup_exc)",
        # API key env-var names being interpolated naively.
        "GOOGLE_AI_API_KEY",
    ]
    for call_src in logger_calls:
        for needle in forbidden_substrings:
            assert needle not in call_src, (
                f"PHI scan: logger call {call_src!r} carries forbidden "
                f"pattern {needle!r}. Always scrub exceptions via "
                "_scrub_secrets and never log clip body bytes."
            )

    # Positive check: at least one logger call routes through the
    # secret scrub. Guards against a future refactor that drops the
    # scrub entirely.
    assert any(
        "_scrub_secrets(" in call for call in logger_calls
    ), (
        "Expected at least one probe.py logger call to route the "
        "exception through _scrub_secrets — none found."
    )


# ── AC-10 — no session persistence ────────────────────────────────────────


async def test_probe_does_not_create_session_row(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-10: the probe never creates a session row.

    Patches the session repository's `create_session` to a `MagicMock`
    and asserts it's never called. The DB dependency itself is already
    a `MagicMock` per the `app_client` fixture, but this test
    explicitly proves the probe doesn't route through any session
    write code path.
    """
    mock_provider_call.return_value = _valid_frame_caption()

    with patch(
        "app.modules.session.service.create_session", new_callable=AsyncMock
    ) as session_create_mock, patch(
        "app.modules.session.service.get_session", new_callable=AsyncMock
    ) as session_get_mock:
        data, files, params = _multipart(body_bytes=fixture_clip_bytes)
        response = await app_client.post(
            "/api/v1/admin/probe/vision-clip",
            headers=admin_headers,
            data=data,
            files=files,
            params=params,
        )

    assert response.status_code == 200
    session_create_mock.assert_not_called()
    session_get_mock.assert_not_called()


# ── AC-11 — temp S3 object always deleted ─────────────────────────────────


async def test_probe_deletes_temp_s3_object_on_success(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-11 (success branch): probe writes then deletes the temp S3
    object on a successful provider call.

    Asserts: put_object called once under `probe/<probe_id>.mp4`,
    delete_object called once with the SAME key.
    """
    mock_provider_call.return_value = _valid_frame_caption()

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200
    mock_s3.put_object.assert_called_once()
    mock_s3.delete_object.assert_called_once()
    put_key = mock_s3.put_object.call_args.kwargs["Key"]
    delete_key = mock_s3.delete_object.call_args.kwargs["Key"]
    assert put_key.startswith("probe/")
    assert put_key.endswith(".mp4")
    assert put_key == delete_key


async def test_probe_deletes_temp_s3_object_on_failure(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-11 (failure branch): probe deletes the temp S3 object even
    when the provider raises."""
    mock_provider_call.side_effect = ProviderError("gemini", "boom")

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    mock_s3.delete_object.assert_called_once()


# ── AC-13 — bundled fixture validity ──────────────────────────────────────


def test_bundled_probe_clip_is_valid_mp4(fixture_clip_bytes: bytes) -> None:
    """AC-13: the bundled fixture loads, is < 50 KB, carries the MP4
    magic bytes, and is not empty.

    Doesn't require ffprobe at test time (that check happens in the
    verification gate via a shell `ffprobe` invocation). This test
    is a smoke check that the fixture is committed correctly.
    """
    assert len(fixture_clip_bytes) > 0
    assert len(fixture_clip_bytes) < 50 * 1024, (
        f"Probe fixture grew to {len(fixture_clip_bytes)} bytes — "
        "regenerate via the recipe in tests/fixtures/README.md."
    )
    # Standard MP4 box header: `ftyp` box at offset 4-8.
    assert fixture_clip_bytes[4:8] == b"ftyp", (
        "Probe fixture is not a valid MP4 (missing `ftyp` box header)."
    )


# ── AC-14 — provider_override resolves through the registry ───────────────


async def test_probe_provider_override_resolves_alternate(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-14: provider_override='openai' resolves through
    `get_vision_provider_for_kind` and the response carries
    `provider_used='openai'`.

    Validates Open/Closed: the probe works for any provider in the
    `VisionProviderKey` enum without code changes to the handler.
    """
    mock_provider_call.return_value = _valid_frame_caption(provider="openai")

    data, files, params = _multipart(
        body_bytes=fixture_clip_bytes, provider_override="openai"
    )
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider_used"] == "openai"
    # P1-FU-FFMPEG: read the model id from the provider's `_MODEL`
    # constant so a future bump there propagates without a test edit.
    assert payload["model_id"] == _OPENAI_MODEL


async def test_probe_provider_override_rejects_invalid_value(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """Invalid provider_override (not in VisionProviderKey) → 422
    from Pydantic Enum validation, no provider call."""
    data, files, params = _multipart(
        body_bytes=fixture_clip_bytes, provider_override="not-a-real-provider"
    )
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    # FastAPI surfaces invalid Enum form fields as 422.
    assert response.status_code == 422, response.text
    mock_provider_call.assert_not_called()


# ── AC-15 — API key scrub on error_message ────────────────────────────────


async def test_probe_scrubs_api_key_from_error_message(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_provider_call: AsyncMock,
) -> None:
    """AC-15: a leaked API key in the provider exception is replaced
    with `***REDACTED***` before the diagnostic crosses the wire.

    Defensive: provider SDKs sometimes include URLs with `?key=…` in
    their exception reprs. The probe scrubs before returning.
    """
    leaked_key = "AIzaSyD8x2vMnPq7Wr3LkJzXcVbNmAaSdFgHjKl"
    mock_provider_call.side_effect = ProviderError(
        "gemini",
        f"auth failed: {leaked_key}",
    )

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is False
    assert leaked_key not in payload["error_message"], (
        "API key leaked through the diagnostic — _scrub_secrets failed."
    )
    assert "***REDACTED***" in payload["error_message"]
