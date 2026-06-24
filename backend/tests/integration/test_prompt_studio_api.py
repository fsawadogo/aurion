"""Integration tests for the Prompt Studio authoring API (PS-03, MVP #524).

Drives the ADMIN-only /api/v1/admin/prompt-studio surface through a real ASGI
client + Postgres: create a prompt, save versions, list the library, read
detail, and the validation / role gates.

DB strategy mirrors ``tests/integration/test_prompt_overrides.py``: real
Postgres required (skipped at collection if unreachable); each test runs in an
outer transaction + SAVEPOINT rolled back at teardown.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import AsyncGenerator

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.types import UserRole  # noqa: E402

_BASE = "/api/v1/admin/prompt-studio"
_JOB = "note_generation"
_WELL_FORMED = (
    "You are a clinical documentation assistant. Describe only what was "
    "directly captured during the encounter. Document the patient's stated "
    "concerns and observed findings. Do not interpret, do not diagnose, and "
    "do not infer clinical meaning."
)

# ── Postgres reachability gate ──────────────────────────────────────────────

_PG_HOST = os.getenv("AURION_TEST_PG_HOST", "localhost")
_PG_PORT = int(os.getenv("AURION_TEST_PG_PORT", "5434"))
_PG_USER = os.getenv("AURION_TEST_PG_USER", "aurion")
_PG_PASS = os.getenv("AURION_TEST_PG_PASS", "aurion")
_PG_DB = os.getenv("AURION_TEST_PG_DB", "aurion")
DATABASE_URL = os.getenv(
    "AURION_TEST_DATABASE_URL",
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/{_PG_DB}",
)


def _pg_reachable() -> tuple[bool, str]:
    try:
        with socket.create_connection((_PG_HOST, _PG_PORT), timeout=0.5):
            pass
    except OSError as e:
        return False, f"TCP connect to {_PG_HOST}:{_PG_PORT} failed: {e}"
    try:
        import asyncpg  # noqa: F401

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
    except Exception as e:  # noqa: BLE001
        return False, f"asyncpg login failed: {e}"


_PG_OK, _PG_SKIP_REASON = _pg_reachable()
pytestmark = pytest.mark.skipif(
    not _PG_OK,
    reason=(
        "Aurion Postgres not available — start `docker compose up -d postgres`. "
        f"({_PG_SKIP_REASON})"
    ),
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
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
    from app.core.database import get_db
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://aurion.test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _seed_user(db: AsyncSession, role: UserRole) -> uuid.UUID:
    from app.core.models import UserModel

    uid = uuid.uuid4()
    db.add(
        UserModel(
            id=uid,
            email=f"{uid}@aurion.test",
            password_hash="x",
            full_name="Test User",
            role=role,
        )
    )
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession) -> tuple[uuid.UUID, dict[str, str]]:
    uid = await _seed_user(db_session, UserRole.ADMIN)
    return uid, {"Authorization": f"Bearer ADMIN:{uid}"}


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_prompt_happy_path(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    _, headers = admin
    r = await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": _JOB, "name": "Tighter PE detail", "text": _WELL_FORMED},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["job_id"] == _JOB
    assert body["name"] == "Tighter PE detail"
    assert len(body["versions"]) == 1
    assert body["versions"][0]["version_no"] == 1
    assert body["versions"][0]["text"] == _WELL_FORMED


@pytest.mark.asyncio
async def test_create_uploaded_text_is_validated_for_descriptive_mode(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    """An uploaded/pasted prompt missing the 'do not interpret/diagnose' anchor
    is rejected with the specific group index."""
    _, headers = admin
    missing_anchor = "You are a clinical assistant. Describe what was captured."
    r = await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": _JOB, "name": "Bad", "text": missing_anchor},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "missing_descriptive_anchor"
    assert detail["missing_anchor_group"] == 1


@pytest.mark.asyncio
async def test_create_rejects_banned_phrase(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    _, headers = admin
    poisoned = _WELL_FORMED + " Then diagnose the patient."
    r = await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": _JOB, "name": "Bad", "text": poisoned},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "banned_phrase"
    assert detail["matched_phrase"] == "diagnose the patient"


@pytest.mark.asyncio
async def test_create_rejects_unknown_job(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    _, headers = admin
    r = await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": "not_a_real_job", "name": "X", "text": _WELL_FORMED},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_save_version_appends_monotonically(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    _, headers = admin
    created = await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": _JOB, "name": "Iterate", "text": _WELL_FORMED},
    )
    prompt_id = created.json()["id"]
    v2_text = _WELL_FORMED + " Capture range of motion in degrees as stated."
    r = await app_client.post(
        f"{_BASE}/prompts/{prompt_id}/versions",
        headers=headers,
        json={"text": v2_text},
    )
    assert r.status_code == 201, r.text
    assert r.json()["version_no"] == 2
    assert r.json()["text"] == v2_text

    detail = await app_client.get(f"{_BASE}/prompts/{prompt_id}", headers=headers)
    assert [v["version_no"] for v in detail.json()["versions"]] == [1, 2]


@pytest.mark.asyncio
async def test_save_version_unknown_prompt_404(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    _, headers = admin
    r = await app_client.post(
        f"{_BASE}/prompts/{uuid.uuid4()}/versions",
        headers=headers,
        json={"text": _WELL_FORMED},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_library_lists_created_prompt(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    _, headers = admin
    await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": _JOB, "name": "In library", "text": _WELL_FORMED},
    )
    r = await app_client.get(f"{_BASE}/prompts", headers=headers)
    assert r.status_code == 200, r.text
    names = {p["name"]: p for p in r.json()}
    assert "In library" in names
    assert names["In library"]["latest_version_no"] == 1
    assert names["In library"]["job_id"] == _JOB


@pytest.mark.asyncio
async def test_jobs_endpoint_exposes_registry_default(
    app_client: AsyncClient, admin: tuple[uuid.UUID, dict[str, str]]
) -> None:
    from app.modules.prompts import PROMPTS

    _, headers = admin
    r = await app_client.get(f"{_BASE}/jobs", headers=headers)
    assert r.status_code == 200, r.text
    jobs = {j["job_id"]: j for j in r.json()}
    assert _JOB in jobs
    assert jobs[_JOB]["system_prompt"] == PROMPTS[_JOB].system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["CLINICIAN", "EVAL_TEAM", "COMPLIANCE_OFFICER"])
async def test_non_admin_forbidden(app_client: AsyncClient, role: str) -> None:
    """Authoring is ADMIN-only in this slice."""
    headers = {"Authorization": f"Bearer {role}:{uuid.uuid4()}"}
    r = await app_client.post(
        f"{_BASE}/prompts",
        headers=headers,
        json={"job_id": _JOB, "name": "X", "text": _WELL_FORMED},
    )
    assert r.status_code == 403, r.text
