r"""Error-hardening regression tests: CORS on every error + UUID path guards.

Two defects this locks down (both surfaced as a browser-side CORS error
masking a server 500):

  1. A malformed (non-UUID) path param used to raise an uncaught
     ``ValueError`` deep in ``uuid.UUID(...)`` → 500 with NO
     ``Access-Control-Allow-Origin`` header. The offending params are now
     typed ``uuid.UUID`` so FastAPI returns a framework-level 422 from the
     ``RequestValidationError`` handler, which runs INSIDE ``CORSMiddleware``
     and therefore carries CORS headers.

  2. Any *other* unhandled exception still 500'd without CORS headers because
     Starlette's ``ServerErrorMiddleware`` sits OUTSIDE ``CORSMiddleware``. A
     global ``@app.exception_handler(Exception)`` now returns a PHI-free 500
     and re-applies the CORS headers manually.

Runs in the CI unit lane (``tests/unit/``): the DB dependency is a
``MagicMock`` (no Postgres / LocalStack), auth is a dev-token bearer
(``APP_ENV=local``), and every request sends ``Origin: http://localhost:3000``
so ``CORSMiddleware`` actually fires.
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

_ALLOWED_ORIGIN = "http://localhost:3000"


def _headers(role: str, *, origin: str = _ALLOWED_ORIGIN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {role}:{uuid.uuid4()}",
        "Origin": origin,
    }


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    from app.core.database import get_db
    from app.main import app

    async def _yield_mock_db() -> AsyncGenerator[MagicMock, None]:
        db = MagicMock()
        result = MagicMock()
        # _ensure_active + get_session: absent rows everywhere.
        result.scalar_one_or_none.return_value = None
        result.scalar.return_value = 0
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        yield db

    app.dependency_overrides[get_db] = _yield_mock_db
    try:
        # raise_app_exceptions=False so ServerErrorMiddleware's re-raise (it
        # always re-raises after invoking the handler) doesn't surface in the
        # test client — we want to inspect the 500 response it produced.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://aurion.test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_bad_uuid_admin_session_returns_422_not_500(
    app_client: AsyncClient,
) -> None:
    """Core regression: pre-fix this was a 500 with NO CORS header.

    The path param is now ``uuid.UUID``-typed, so a non-UUID value is rejected
    by FastAPI validation (422) before the handler runs, and the response
    carries CORS headers because the validation handler lives inside
    ``CORSMiddleware``.
    """
    resp = await app_client.get(
        "/api/v1/admin/sessions/not-a-uuid", headers=_headers("ADMIN")
    )
    assert resp.status_code == 422, resp.text
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN


async def test_bad_uuid_admin_media_returns_422(app_client: AsyncClient) -> None:
    resp = await app_client.get(
        "/api/v1/admin/media/not-a-uuid/download-urls",
        headers=_headers("ADMIN"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN


async def test_bad_uuid_admin_user_reset_password_returns_422(
    app_client: AsyncClient,
) -> None:
    resp = await app_client.post(
        "/api/v1/admin/users/not-a-uuid/reset-password",
        headers=_headers("ADMIN"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN


async def test_bad_uuid_admin_user_update_returns_422(
    app_client: AsyncClient,
) -> None:
    resp = await app_client.patch(
        "/api/v1/admin/users/not-a-uuid",
        headers=_headers("ADMIN"),
        json={"is_active": False},
    )
    assert resp.status_code == 422, resp.text
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN


async def test_unhandled_exception_returns_500_with_cors_and_phi_free_body(
    app_client: AsyncClient,
) -> None:
    """An unhandled exception 500 must carry CORS headers and leak nothing.

    Monkeypatch the session lookup the admin detail handler calls so it raises
    a RuntimeError whose message embeds a PHI sentinel. The global handler must
    return a fixed generic body, keep the sentinel out of the response, and
    re-apply the CORS headers.
    """
    from app.api.v1.admin import sessions as sessions_module

    with patch.object(
        sessions_module,
        "get_session_or_404",
        new=AsyncMock(side_effect=RuntimeError("boom SENTINEL-PHI")),
    ):
        resp = await app_client.get(
            f"/api/v1/admin/sessions/{uuid.uuid4()}",
            headers=_headers("ADMIN"),
        )

    assert resp.status_code == 500, resp.text
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert resp.json() == {"detail": "Internal server error"}
    # PHI / internals must never reach the client.
    assert "SENTINEL-PHI" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


async def test_404_unknown_uuid_keeps_cors(app_client: AsyncClient) -> None:
    """A well-formed but absent session UUID → 404, still CORS-headed.

    Locks in that ``HTTPException`` responses (inner ExceptionMiddleware,
    inside CORS) already carry CORS headers — no regression there.
    """
    resp = await app_client.get(
        f"/api/v1/admin/sessions/{uuid.uuid4()}", headers=_headers("ADMIN")
    )
    assert resp.status_code == 404, resp.text
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN


async def test_disallowed_origin_not_echoed_on_500(
    app_client: AsyncClient,
) -> None:
    """A disallowed Origin must NOT receive an echoed allow-origin on a 500."""
    from app.api.v1.admin import sessions as sessions_module

    with patch.object(
        sessions_module,
        "get_session_or_404",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        resp = await app_client.get(
            f"/api/v1/admin/sessions/{uuid.uuid4()}",
            headers=_headers("ADMIN", origin="http://evil.test"),
        )

    assert resp.status_code == 500, resp.text
    assert resp.headers.get("access-control-allow-origin") != "http://evil.test"
