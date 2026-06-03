"""Pre-verifies the fallback chain path the Dockerfile fix enables.

P1-FU-FFMPEG — bug 1 background
-------------------------------
Live probes against `api-dev.aurionclinical.com` with
`?provider_override=anthropic` AND `?provider_override=openai` both
failed with:

    "ffmpeg binary not found on PATH -- clip-to-still fallback requires
     the system `ffmpeg` binary to be installed."

The midpoint-still fallback (`_clip_to_still.extract_midpoint_still`)
shells out to `ffmpeg`. Without the binary in the runtime image, both
non-native vision providers (OpenAI + Anthropic) crash before issuing
the model call. The fallback chain
(`get_vision_provider_with_fallback`) cannot recover from a missing
OS-level dependency.

The Dockerfile fix in this PR adds `ffmpeg` to the apt-get install line
and verifies it with `RUN ffmpeg -version`. This test pre-verifies the
end-to-end success path that the fix unblocks: the probe runs through
the Anthropic provider (override), the (now-available) ffmpeg-backed
still extractor is mocked to succeed, and the response carries the
expected `degraded_to_frame=true` flag.

Scope boundary
--------------
This test does NOT shell out to ffmpeg itself — that's an OS concern.
It pins the Python-side contract: the response from a successful
fallback round trip MUST carry the degraded-frame flag and identify
the override provider. The Dockerfile + the `RUN ffmpeg -version`
build step is the OS-side verification; this test is its Python-side
mirror.

DRY / SOLID
-----------
* Reuses the same fixture and mock pattern as
  `tests/integration/test_vision_clip_probe.py` (no third copy of the
  helpers).
* Single-responsibility: only the fallback-chain end-to-end path.
* No PHI — synthetic clip body, synthetic anchor.
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

from app.core.types import FrameCaption, MaskedFrame  # noqa: E402
from app.modules.providers.vision.anthropic import _MODEL as _ANTHROPIC_MODEL  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def fixture_clip_bytes() -> bytes:
    """The bundled probe MP4 — used as the upload body, NOT decoded.

    The real `extract_midpoint_still` is mocked in every test; the body
    just needs to be a valid MP4 so the content-type + size validation
    at the probe boundary passes.
    """
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
    """ASGI in-process client; the DB dependency is mocked because the
    probe doesn't touch the DB."""
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
    """Replace AuditLogService so writes never touch DynamoDB."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


@pytest.fixture
def mock_s3():
    """Patch the S3 client factory inside the probe module."""
    client = MagicMock()
    client.put_object = MagicMock(return_value={"ETag": "stub"})
    client.delete_object = MagicMock(return_value={})
    with patch("app.api.v1.admin.probe.get_s3_client", return_value=client):
        yield client


def _multipart(
    *, body_bytes: bytes, provider_override: str
) -> tuple[dict, dict, dict]:
    """Build (data, files, params) for the probe POST. The override
    flows as a query string (P1-FU-FFMPEG bug 2 fix)."""
    files = {"clip": ("probe_clip.mp4", body_bytes, "video/mp4")}
    return {}, files, {"provider_override": provider_override}


# ── AC-1: ffmpeg-enabled Anthropic fallback round trip ─────────────────────


@pytest.mark.asyncio
async def test_probe_anthropic_override_with_ffmpeg_returns_degraded_caption(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """When `?provider_override=anthropic` flows through the probe AND
    `extract_midpoint_still` succeeds (mock stands in for the ffmpeg
    binary that the Dockerfile fix installs), the end-to-end response
    must:

      * status 200 with `success=true`,
      * `provider_used="anthropic"`,
      * `model_id` matches the provider's `_MODEL` constant (bug-3 fix),
      * `caption.evidence_kind="clip"`,
      * `caption.degraded_to_frame=true`,
      * `caption.duration_ms` echoes the clip duration.

    This is the exact path the live probe couldn't reach in production
    before this PR — both because the override was silently ignored
    (bug 2) AND because the still-fallback crashed at `ffmpeg not found`
    (bug 1). With both fixes in place, the path returns a real
    diagnostic.
    """
    # Synthetic still that `extract_midpoint_still` "returns" — the
    # mock stands in for the real ffmpeg invocation that the Dockerfile
    # fix enables in production.
    synthetic_still = MaskedFrame(
        frame_id="probe_seg_test_midstill",
        session_id="00000000-0000-0000-0000-000000000000",
        timestamp_ms=1000,
        s3_key="probe/synthetic.midstill.jpg",
        masking_confirmed=True,
    )

    # The Anthropic provider's `caption_frame` returns this — same
    # shape as the real Claude response after fence-stripping + JSON
    # parse. `caption_clip` then flips evidence_kind / duration_ms /
    # degraded_to_frame on the way out.
    inner_frame_caption = FrameCaption(
        frame_id=synthetic_still.frame_id,
        session_id=synthetic_still.session_id,
        timestamp_ms=synthetic_still.timestamp_ms,
        audio_anchor_id="probe_seg_test",
        provider_used="anthropic",
        visual_description=(
            "A solid blue test pattern with no clinical content."
        ),
        confidence="low",
        confidence_reason="No clinically relevant content visible.",
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
        evidence_kind="frame",
        duration_ms=None,
        degraded_to_frame=False,
    )

    # Patch `extract_midpoint_still` at the call site inside
    # `anthropic.py` so the provider's `caption_clip` skips the real
    # ffmpeg subprocess. This is the surface the Dockerfile fix
    # unblocks in production.
    with patch(
        "app.modules.providers.vision.anthropic.extract_midpoint_still",
        new=AsyncMock(return_value=synthetic_still),
    ) as mock_extract, patch(
        "app.modules.providers.vision.anthropic.AnthropicVisionProvider.caption_frame",
        new=AsyncMock(return_value=inner_frame_caption),
    ) as mock_caption_frame:
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

    # Single resolution + single round trip through the fallback path.
    mock_extract.assert_awaited_once()
    mock_caption_frame.assert_awaited_once()

    # End-to-end response semantics. The probe identifies the override
    # provider (bug 2 fix), and the still-fallback flag rides through.
    assert payload["success"] is True
    assert payload["provider_used"] == "anthropic", (
        f"Expected provider_used='anthropic' when override='anthropic'; "
        f"got {payload['provider_used']!r}. Bug 2 (probe param binding) "
        f"has re-emerged."
    )
    assert payload["model_id"] == _ANTHROPIC_MODEL, (
        f"Expected model_id to match anthropic._MODEL ({_ANTHROPIC_MODEL!r}); "
        f"got {payload['model_id']!r}. Bug 3 (stale model_id constant) has "
        f"re-emerged."
    )
    assert payload["caption"] is not None
    assert payload["caption"]["evidence_kind"] == "clip"
    assert payload["caption"]["degraded_to_frame"] is True, (
        "Caption must carry degraded_to_frame=True when the still "
        "fallback was taken — operators rely on this flag to know the "
        "Anthropic path did NOT consume the clip natively."
    )
    assert payload["caption"]["duration_ms"] is not None


# ── AC-2: ffmpeg-enabled OpenAI fallback round trip ────────────────────────


@pytest.mark.asyncio
async def test_probe_openai_override_with_ffmpeg_returns_degraded_caption(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """Parallel coverage for `?provider_override=openai`.

    OpenAI uses the SAME `extract_midpoint_still` helper as Anthropic
    (DRY proven by `test_clip_captioning.TestSharedClipToStillHelper`),
    so this case exercises the SECOND production-broken path the live
    probe could not reach.
    """
    from app.modules.providers.vision.openai import _MODEL as _OPENAI_MODEL

    synthetic_still = MaskedFrame(
        frame_id="probe_seg_test_midstill",
        session_id="00000000-0000-0000-0000-000000000000",
        timestamp_ms=1000,
        s3_key="probe/synthetic.midstill.jpg",
        masking_confirmed=True,
    )

    inner_frame_caption = FrameCaption(
        frame_id=synthetic_still.frame_id,
        session_id=synthetic_still.session_id,
        timestamp_ms=synthetic_still.timestamp_ms,
        audio_anchor_id="probe_seg_test",
        provider_used="openai",
        visual_description=(
            "A solid blue test pattern with no clinical content."
        ),
        confidence="low",
        confidence_reason="No clinically relevant content visible.",
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
        evidence_kind="frame",
        duration_ms=None,
        degraded_to_frame=False,
    )

    with patch(
        "app.modules.providers.vision.openai.extract_midpoint_still",
        new=AsyncMock(return_value=synthetic_still),
    ) as mock_extract, patch(
        "app.modules.providers.vision.openai.OpenAIVisionProvider.caption_frame",
        new=AsyncMock(return_value=inner_frame_caption),
    ) as mock_caption_frame:
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
    mock_extract.assert_awaited_once()
    mock_caption_frame.assert_awaited_once()
    assert payload["success"] is True
    assert payload["provider_used"] == "openai"
    assert payload["model_id"] == _OPENAI_MODEL
    assert payload["caption"]["evidence_kind"] == "clip"
    assert payload["caption"]["degraded_to_frame"] is True


# ── AC-3: ffmpeg-absent path surfaces as a structured diagnostic ──────────


@pytest.mark.asyncio
async def test_probe_anthropic_fallback_surfaces_ffmpeg_missing_as_diagnostic(
    app_client: AsyncClient,
    admin_headers: dict[str, str],
    fixture_clip_bytes: bytes,
    mock_audit: MagicMock,
    mock_s3: MagicMock,
) -> None:
    """Regression guard for the ORIGINAL production symptom: when
    `extract_midpoint_still` raises `FileNotFoundError` (the live
    pre-fix behaviour), the probe MUST still return a 200 with a
    structured diagnostic — never crash, never 500.

    This pins the probe's "never re-raise" contract for the specific
    failure mode that surfaced live. Even after the Dockerfile fix
    installs ffmpeg, a future regression (e.g. a base-image swap that
    drops ffmpeg) must surface here as a structured failure rather
    than a 500.
    """
    with patch(
        "app.modules.providers.vision.anthropic.extract_midpoint_still",
        new=AsyncMock(
            side_effect=FileNotFoundError(
                "ffmpeg binary not found on PATH -- clip-to-still "
                "fallback requires the system `ffmpeg` binary to be "
                "installed."
            )
        ),
    ):
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

    # 200 + structured failure — the probe's "never re-raise" contract
    # holds even when an OS-level dep is missing.
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_type"] in {"Exception", "FileNotFoundError"}
    assert "ffmpeg" in payload["error_message"].lower()
    assert payload["provider_used"] == "anthropic"
