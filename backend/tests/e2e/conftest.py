"""Shared fixtures for the E2E smoke test suite.

Design notes — see ACCEPTANCE.md for the full plan.

  * `db_engine` — module-scoped engine against the developer's local
    Postgres. Tests are skipped at collection time if Postgres is not
    reachable on localhost:5432.
  * `db_session` — function-scoped. Opens one connection per test and
    wraps it in an outer transaction + nested SAVEPOINT so every test
    gets a clean slate without DROP/CREATE between runs. Route handlers
    that call `await db.flush()` write to the SAVEPOINT and are visible
    in-test; teardown rolls everything back.
  * `app_client` — httpx.AsyncClient with ASGITransport. Overrides
    `get_db` so the FastAPI dependency yields the test's transactional
    session. The FastAPI lifespan is *not* invoked (ASGITransport
    doesn't run lifespan by default), so the AppConfig poller never
    starts and we don't need to mock the boto3 layer for that path.
  * `mock_audit_log` (autouse) — replaces the module-level
    AuditLogService singleton with an AsyncMock so audit writes don't
    touch DynamoDB. Tests can assert against `mock_audit_log.write_event`.
"""

from __future__ import annotations

import os
import socket
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# IMPORTANT: env vars must be set before the FastAPI app imports load. The
# tests/__init__ + conftest hierarchy means this conftest is imported when
# pytest collects e2e tests, which is when `from app.main import app` first
# runs. Keep these at the top of the file.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

_PG_HOST = os.getenv("AURION_TEST_PG_HOST", "localhost")
# docker-compose maps the aurion Postgres to host port 5434 (5432 is the
# in-container port). 5434 is the contract.
_PG_PORT = int(os.getenv("AURION_TEST_PG_PORT", "5434"))
_PG_USER = os.getenv("AURION_TEST_PG_USER", "aurion")
_PG_PASS = os.getenv("AURION_TEST_PG_PASS", "aurion")
_PG_DB = os.getenv("AURION_TEST_PG_DB", "aurion")

DATABASE_URL = os.getenv(
    "AURION_TEST_DATABASE_URL",
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/{_PG_DB}",
)


def _pg_reachable() -> tuple[bool, str]:
    """Return (reachable, reason). Reachable means we can both open the
    TCP socket *and* authenticate with the aurion credentials — a bare
    port-open check would yield a confusing auth error inside a fixture
    when the host has a non-aurion Postgres listening on 5432."""
    try:
        with socket.create_connection((_PG_HOST, _PG_PORT), timeout=0.5):
            pass
    except OSError as e:
        return False, f"TCP connect to {_PG_HOST}:{_PG_PORT} failed: {e}"

    try:
        import asyncpg  # noqa: F401  — verifies driver presence

        async def _probe() -> None:
            conn = await asyncpg.connect(
                host=_PG_HOST,
                port=_PG_PORT,
                user=_PG_USER,
                password=_PG_PASS,
                database=_PG_DB,
                timeout=1.0,
            )
            await conn.close()

        asyncio.new_event_loop().run_until_complete(_probe())
        return True, ""
    except Exception as e:  # noqa: BLE001 — message goes to skip reason
        return False, f"asyncpg login as {_PG_USER}@{_PG_HOST}:{_PG_PORT}/{_PG_DB} failed: {e}"


_PG_OK, _PG_SKIP_REASON = _pg_reachable()


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip every test in this directory if the aurion Postgres is
    unreachable. `pytestmark` in conftest.py doesn't propagate to
    sibling test files, hence the hook."""
    if _PG_OK:
        return
    skip_marker = pytest.mark.skip(
        reason=f"Aurion Postgres not available — start `docker compose up -d postgres`. "
        f"({_PG_SKIP_REASON})"
    )
    for item in items:
        item.add_marker(skip_marker)


@pytest_asyncio.fixture
async def db_engine():
    """Engine pointed at the developer's local Postgres.

    Function-scoped because pytest-asyncio creates one event loop per
    test by default; an asyncpg connection pool bound to a longer-lived
    loop trips "Task attached to a different loop" on the second test.
    Connection-pool overhead is negligible for a smoke suite of this
    size; if it ever does hurt, the fix is to align loop_scope and
    fixture scope together (both `session` or both default).
    """
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """One connection, one outer transaction, one SAVEPOINT per test.

    The route handlers under test call `await db.flush()` and rely on
    the FastAPI dependency to commit. Here, the fixture's outer
    transaction is *always* rolled back at teardown — so even a
    "successful" route handler leaves no data behind.
    """
    async with db_engine.connect() as connection:
        outer = await connection.begin()
        try:
            factory = async_sessionmaker(
                bind=connection,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                yield session
        finally:
            if outer.is_active:
                await outer.rollback()


@pytest_asyncio.fixture
async def app_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """ASGI in-process client.

    Imported lazily so the conftest can short-circuit when Postgres is
    unreachable without forcing the full FastAPI app to load.
    """
    from app.core.database import get_db
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        # Yield the same transactional session the test holds; do *not*
        # commit or close — the outer fixture owns lifecycle.
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://aurion.test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def mock_audit_log(monkeypatch):
    """Replace the AuditLogService singleton with an AsyncMock.

    Tests can pull this fixture by name to assert on emitted events;
    autouse=True means every E2E test gets the patch even if it doesn't
    explicitly request the fixture (audit writes happen on almost every
    route).
    """
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    mock_service.get_session_events = AsyncMock(return_value=[])

    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


@pytest.fixture
def clinician_user() -> tuple[uuid.UUID, str]:
    """Return (user_id, bearer_token) for a CLINICIAN.

    Token format is the dev-mode contract from
    `app.modules.auth.service._parse_dev_token`: `<role>:<user_id>`.
    """
    user_id = uuid.uuid4()
    token = f"CLINICIAN:{user_id}"
    return user_id, token


@pytest.fixture
def auth_headers(clinician_user) -> dict[str, str]:
    _, token = clinician_user
    return {"Authorization": f"Bearer {token}"}
