r"""Integration tests for the admin Captured Media endpoints (#338).

Exercised end-to-end through the ASGI app so the route registration, the
``require_role`` HTTP gate, and the flag gate are all covered together. The
DB dependency yields a MagicMock whose result object answers every access
shape the handlers and ``_ensure_active`` need (no LocalStack / Postgres).
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

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.v1.admin import media as media_module  # noqa: E402
from app.modules.config.schema import (  # noqa: E402
    AppConfigSchema,
    FeatureFlagsConfig,
)


def _config(*, retention: bool) -> AppConfigSchema:
    return AppConfigSchema(
        feature_flags=FeatureFlagsConfig(media_review_retention_enabled=retention)
    )


def _headers(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{uuid.uuid4()}"}


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    from app.core.database import get_db
    from app.main import app

    async def _yield_mock_db() -> AsyncGenerator[MagicMock, None]:
        db = MagicMock()
        result = MagicMock()
        # _ensure_active: anything that is not literally False = active.
        result.scalar_one_or_none.return_value = None
        result.scalar.return_value = 0
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        yield db

    app.dependency_overrides[get_db] = _yield_mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://aurion.test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_list_flag_off_returns_403(app_client: AsyncClient) -> None:
    with patch.object(media_module, "get_config", return_value=_config(retention=False)):
        resp = await app_client.get("/api/v1/admin/media", headers=_headers("ADMIN"))
    assert resp.status_code == 403, resp.text


async def test_list_clinician_blocked_403(app_client: AsyncClient) -> None:
    with patch.object(media_module, "get_config", return_value=_config(retention=True)):
        resp = await app_client.get(
            "/api/v1/admin/media", headers=_headers("CLINICIAN")
        )
    assert resp.status_code == 403, resp.text


async def test_list_compliance_officer_allowed(app_client: AsyncClient) -> None:
    """COMPLIANCE_OFFICER can VIEW the list (empty here, but 200)."""
    with patch.object(media_module, "get_config", return_value=_config(retention=True)):
        resp = await app_client.get(
            "/api/v1/admin/media", headers=_headers("COMPLIANCE_OFFICER")
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["retention_days"] == 7


async def test_download_compliance_officer_blocked_403(app_client: AsyncClient) -> None:
    """COMPLIANCE_OFFICER is view-only — no download URLs."""
    with patch.object(media_module, "get_config", return_value=_config(retention=True)):
        resp = await app_client.get(
            f"/api/v1/admin/media/{uuid.uuid4()}/download-urls",
            headers=_headers("COMPLIANCE_OFFICER"),
        )
    assert resp.status_code == 403, resp.text


async def test_download_flag_off_returns_403(app_client: AsyncClient) -> None:
    with patch.object(media_module, "get_config", return_value=_config(retention=False)):
        resp = await app_client.get(
            f"/api/v1/admin/media/{uuid.uuid4()}/download-urls",
            headers=_headers("ADMIN"),
        )
    assert resp.status_code == 403, resp.text
