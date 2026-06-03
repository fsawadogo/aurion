"""Unit tests for the probe endpoint's provider_override resolution.

P1-FU-PROBE-BUGS — bug 1: the probe was supposedly threading
``provider_override`` through to ``registry.get_vision_provider_for_kind``
but the live response always showed ``provider_used="gemini"`` even when
``provider_override="anthropic"`` was supplied. Root cause: TWO
independent resolution call sites — the response-shape resolver and the
registry call — could drift.

These tests pin the invariant:

  * the registry is called with the override (or default) exactly once,
  * the response's ``provider_used`` matches the registry's argument,
  * no override means the AppConfig default flows through both call
    sites.

The tests mock the registry call surface so we can assert the override
argument directly — no real provider instantiation, no real HTTP, no
real S3.
"""

from __future__ import annotations

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

from app.core.types import FrameCaption  # noqa: E402
from app.modules.config.schema import VisionProviderKey  # noqa: E402
from app.modules.providers.vision.anthropic import _MODEL as _ANTHROPIC_MODEL  # noqa: E402
from app.modules.providers.vision.openai import _MODEL as _OPENAI_MODEL  # noqa: E402

# ── Fixtures (compact local versions of the integration ones) ─────────────


@pytest.fixture
def fixture_clip_bytes() -> bytes:
    """The bundled probe MP4."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "fixtures", "probe_clip.mp4"
    )
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer ADMIN:{uuid.uuid4()}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI in-process client; no DB connection required."""
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
    """Replace AuditLogService singleton so writes never touch DynamoDB."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


@pytest.fixture
def mock_s3():
    """Patch the shared S3 client factory inside the probe module."""
    client = MagicMock()
    client.put_object = MagicMock(return_value={"ETag": "stub"})
    client.delete_object = MagicMock(return_value={})
    with patch("app.api.v1.admin.probe.get_s3_client", return_value=client):
        yield client


@pytest.fixture
def mock_registry():
    """Patch get_registry inside probe.py so we can assert the
    `get_vision_provider_for_kind` call arguments — the core bug-1
    invariant.

    Yields a tuple (registry_mock, caption_clip_mock, get_kind_mock):

      * registry_mock — the MagicMock returned by `get_registry()`
      * caption_clip_mock — the AsyncMock on the stub provider; tests
        configure `.return_value=` to drive happy-path responses.
      * get_kind_mock — the MagicMock on
        `registry.get_vision_provider_for_kind`. Tests assert on its
        `.call_args` to verify the override flowed through.
    """
    stub_provider = MagicMock()
    caption_clip_mock = AsyncMock()
    stub_provider.caption_clip = caption_clip_mock

    def _resolve(kind: str, override=None):
        return stub_provider

    with patch("app.api.v1.admin.probe.get_registry") as mock_get_registry:
        registry = MagicMock()
        registry.get_vision_provider_for_kind = MagicMock(side_effect=_resolve)
        mock_get_registry.return_value = registry
        yield registry, caption_clip_mock, registry.get_vision_provider_for_kind


def _multipart(
    *,
    body_bytes: bytes,
    content_type: str = "video/mp4",
    provider_override: str | None = None,
) -> tuple[dict, dict, dict]:
    """Build (data, files, params) for an httpx multipart POST to the probe.

    P1-FU-FFMPEG: `provider_override` is a QUERY-STRING parameter on the
    endpoint (was `Form()`, silently ignored query-string values). The
    `params` dict is forwarded as `?provider_override=…` so these tests
    pin the actual public contract operators consume via curl/Postman.
    """
    data: dict = {}
    params: dict = {}
    if provider_override is not None:
        params["provider_override"] = provider_override
    files = {"clip": ("probe_clip.mp4", body_bytes, content_type)}
    return data, files, params


def _valid_caption(provider: str) -> FrameCaption:
    return FrameCaption(
        frame_id="probe_seg_test_clip",
        session_id="00000000-0000-0000-0000-000000000000",
        timestamp_ms=1000,
        audio_anchor_id="probe_seg_test",
        provider_used=provider,
        visual_description=("A solid blue test pattern with no clinical content."),
        confidence="low",
        confidence_reason="No clinically relevant content visible.",
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
        evidence_kind="clip",
        duration_ms=2000,
        degraded_to_frame=False,
    )


# ── AC-1 — override forwarded to registry as the single resolution ────────


@pytest.mark.asyncio
async def test_probe_provider_override_forwarded_to_registry(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_registry,
) -> None:
    """AC-1: `registry.get_vision_provider_for_kind` is called with
    `('clip', override='anthropic')` exactly ONCE when the request
    carries `provider_override='anthropic'`.

    Locks the single-resolution invariant: no other path inside the
    handler can call the registry, and the override argument cannot
    drift from what the response carries.
    """
    _registry, caption_clip_mock, get_kind_mock = mock_registry
    caption_clip_mock.return_value = _valid_caption(provider="anthropic")

    data, files, params = _multipart(
        body_bytes=fixture_clip_bytes, provider_override="anthropic"
    )
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    # Exactly one resolution call.
    assert get_kind_mock.call_count == 1, (
        f"Expected exactly one registry resolution; got "
        f"{get_kind_mock.call_count} calls — duplicate resolution paths "
        f"have been re-introduced."
    )
    # Argument matches the override (positional kind, keyword override).
    args, kwargs = get_kind_mock.call_args
    assert args == ("clip",) or kwargs.get("kind") == "clip"
    assert kwargs.get("override") == "anthropic", (
        f"Override did not flow through to the registry; got "
        f"kwargs={kwargs!r}"
    )


# ── AC-2 — override alters response.provider_used ─────────────────────────


@pytest.mark.asyncio
async def test_probe_provider_override_alters_provider_used(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_registry,
) -> None:
    """AC-2: With `provider_override='anthropic'`, the response's
    `provider_used` field is 'anthropic' (not the AppConfig default).

    This is the user-visible symptom that bug-1 broke: the live probe
    returned `provider_used='gemini'` no matter what override was sent.
    """
    _registry, caption_clip_mock, _get_kind = mock_registry
    caption_clip_mock.return_value = _valid_caption(provider="anthropic")

    data, files, params = _multipart(
        body_bytes=fixture_clip_bytes, provider_override="anthropic"
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
    assert payload["provider_used"] == "anthropic", (
        f"Response should carry provider_used='anthropic' "
        f"when override='anthropic'; got {payload['provider_used']!r}"
    )
    # P1-FU-FFMPEG (bug 3): model id is read from the provider module's
    # own `_MODEL` constant, NOT a hardcoded duplicate in probe.py. The
    # assertion reads the same source-of-truth so a future model bump
    # in `anthropic.py:_MODEL` doesn't require touching the probe OR
    # this test.
    assert payload["model_id"] == _ANTHROPIC_MODEL, (
        f"Model id should reflect the provider's `_MODEL` constant "
        f"({_ANTHROPIC_MODEL!r}); got {payload['model_id']!r}"
    )


@pytest.mark.asyncio
async def test_probe_provider_override_openai_alters_provider_used(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_registry,
) -> None:
    """AC-2b: parallel coverage for `provider_override='openai'`."""
    _registry, caption_clip_mock, get_kind_mock = mock_registry
    caption_clip_mock.return_value = _valid_caption(provider="openai")

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
    assert payload["model_id"] == _OPENAI_MODEL
    # Registry receives the override as a string (the enum's .value).
    _args, kwargs = get_kind_mock.call_args
    assert kwargs.get("override") == "openai"


# ── AC-3 — no override → AppConfig default flows through both sites ───────


@pytest.mark.asyncio
async def test_probe_no_override_uses_default(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_registry,
) -> None:
    """AC-3: No `provider_override` → the response carries the AppConfig
    default (`vision_clip`) AND the registry is called with that same
    default key. Single resolution path means they cannot diverge.

    We don't hardcode 'gemini' because the AppConfig default could
    change; instead we read the live config snapshot and assert the
    response matches it.
    """
    from app.modules.config.appconfig_client import get_config

    expected_key: VisionProviderKey = get_config().providers.vision_clip

    _registry, caption_clip_mock, get_kind_mock = mock_registry
    caption_clip_mock.return_value = _valid_caption(provider=expected_key.value)

    data, files, params = _multipart(body_bytes=fixture_clip_bytes)  # no override
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider_used"] == expected_key.value, (
        f"Without override, response.provider_used should match the "
        f"AppConfig default {expected_key.value!r}; got "
        f"{payload['provider_used']!r}"
    )
    # Registry called with the SAME key the response carries — locks
    # the single-resolution invariant on the default path too.
    _args, kwargs = get_kind_mock.call_args
    assert kwargs.get("override") == expected_key.value, (
        f"Without override, registry should be called with the resolved "
        f"AppConfig default; got kwargs={kwargs!r}"
    )


# ── AC-1 reinforcement — response.provider_used matches registry call ────


@pytest.mark.asyncio
async def test_probe_response_provider_used_matches_registry_call(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
    mock_registry,
) -> None:
    """AC-1b: For every successful request, the response's
    `provider_used` field equals the `override` keyword passed to
    the registry. This is the LSP-style contract: response and call
    cannot disagree.
    """
    _registry, caption_clip_mock, get_kind_mock = mock_registry
    caption_clip_mock.return_value = _valid_caption(provider="anthropic")

    data, files, params = _multipart(
        body_bytes=fixture_clip_bytes, provider_override="anthropic"
    )
    response = await app_client.post(
        "/api/v1/admin/probe/vision-clip",
        headers=admin_headers,
        data=data,
        files=files,
        params=params,
    )
    assert response.status_code == 200
    payload = response.json()

    _args, kwargs = get_kind_mock.call_args
    assert payload["provider_used"] == kwargs.get("override")
