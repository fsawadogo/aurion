"""Integration tests for GET /api/v1/config (#324 clip cadence floor).

The client-config endpoint returns the AppConfig subset iOS needs. The
clip family (``clip_cadence_seconds``, ``visual_evidence_mode``,
``clip_window_ms``, ``clip_trigger_kinds``) MUST all be emitted: iOS owns
the during-recording cadence timer and gates it on BOTH a non-zero
cadence AND a clips_only/hybrid mode, so withholding ``visual_evidence_mode``
silently disables cadence on-device (the mode defaults to frames_only).

Test isolation mirrors test_clips_endpoint: an in-process ASGI client,
the ``APP_ENV=local`` dev-token bearer shape, and a patched ``get_config``
so no AppConfig/AWS round-trip is needed.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator

# Set env before app import — APP_ENV=local enables the dev-token
# bearer shape `<role>:<user_id>` parsed by `_parse_dev_token`.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.modules.config.schema import (  # noqa: E402
    AppConfigSchema,
    PipelineConfig,
    VisualEvidenceMode,
)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer CLINICIAN:{uuid.uuid4()}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://aurion.test"
    ) as client:
        yield client


async def test_config_includes_clip_cadence_seconds(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    """GET /config surfaces pipeline.clip_cadence_seconds (dev value 30)."""
    cfg = AppConfigSchema(pipeline=PipelineConfig(clip_cadence_seconds=30))
    monkeypatch.setattr("app.api.v1.config.get_config", lambda: cfg)

    response = await app_client.get("/api/v1/config", headers=auth_headers)

    assert response.status_code == 200, response.text
    pipeline = response.json()["pipeline"]
    assert "clip_cadence_seconds" in pipeline
    assert pipeline["clip_cadence_seconds"] == 30


async def test_config_emits_clip_family_so_ios_can_activate_cadence(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    """Regression (zero-clips root cause): iOS only starts the cadence
    driver when BOTH clip_cadence_seconds>0 AND the resolved visual-evidence
    mode is clips_only/hybrid reach the device. The endpoint previously
    emitted clip_cadence_seconds alone, so iOS defaulted the mode to
    frames_only and cadence never ran. Lock that the whole clip family iOS
    decodes is present and that a hybrid+cadence config round-trips."""
    cfg = AppConfigSchema(
        pipeline=PipelineConfig(
            clip_cadence_seconds=30,
            visual_evidence_mode=VisualEvidenceMode.HYBRID,
            clip_window_ms=7000,
        )
    )
    monkeypatch.setattr("app.api.v1.config.get_config", lambda: cfg)

    response = await app_client.get("/api/v1/config", headers=auth_headers)

    assert response.status_code == 200, response.text
    pipeline = response.json()["pipeline"]
    assert pipeline["clip_cadence_seconds"] == 30
    # The field whose absence disabled cadence on-device.
    assert pipeline["visual_evidence_mode"] == "hybrid"
    assert pipeline["clip_window_ms"] == 7000
    assert isinstance(pipeline["clip_trigger_kinds"], list)


async def test_config_clip_cadence_default_off(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    """With the pilot default config, clip_cadence_seconds is 0 (off)."""
    cfg = AppConfigSchema()  # all defaults
    monkeypatch.setattr("app.api.v1.config.get_config", lambda: cfg)

    response = await app_client.get("/api/v1/config", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["pipeline"]["clip_cadence_seconds"] == 0
