"""Integration tests for the clinician schedule routes (`/me/schedule`, #603).

Exercises the real FastAPI routes end-to-end against Postgres + KMS
(APP_ENV=local / LocalStack), proving the contracts the unit tests can't:

  1. Per-clinician scope — a clinician sees ONLY their own entries; another
     clinician's entry is invisible and non-owned PATCH/DELETE returns 404.
  2. Encrypt-at-rest roundtrip — POST stores ciphertext in the column and
     GET returns the decrypted identifier for the owner.
  3. PHI foot-gun — a full-name identifier is 422 and the value is not
     echoed in the response body.
  4. Status transitions through the API — legal transition 200, terminal
     re-open 409.
  5. Non-CLINICIAN roles get 403.

Skips when Postgres isn't reachable (same guard as the other integration
tests); CI provides the DB.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault(
    "AURION_IDENTIFIER_HMAC_KEY", "integration-test-key-schedule"
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import identifier_hash  # noqa: E402
from app.core.models import UserModel  # noqa: E402
from app.core.types import UserRole  # noqa: E402

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
        return False, f"TCP connect failed: {e}"
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
    reason=f"Aurion Postgres not available — {_PG_SKIP_REASON}",
)


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
        async with AsyncClient(
            transport=transport, base_url="http://aurion.test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def reset_hash_cache() -> None:
    identifier_hash.reset_cache_for_tests()


@pytest.fixture(autouse=True)
def mock_audit_log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    mock_service.get_session_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


def _bearer(role: str, user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{user_id}"}


async def _seed_user(
    db_session: AsyncSession, role: UserRole = UserRole.CLINICIAN
) -> uuid.UUID:
    uid = uuid.uuid4()
    db_session.add(
        UserModel(
            id=uid,
            email=f"{uid}@aurion.test",
            password_hash="x",
            full_name="Schedule Test User",
            role=role,
        )
    )
    await db_session.flush()
    return uid


@pytest.mark.asyncio
async def test_create_then_list_roundtrips_decrypted_identifier(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST stores ciphertext; GET returns the decrypted identifier and the
    DB column is NOT the plaintext bytes."""
    clinician = await _seed_user(db_session)
    await db_session.commit()

    created = await app_client.post(
        "/api/v1/me/schedule",
        headers=_bearer("CLINICIAN", clinician),
        json={"patient_identifier": "MRN-SCHED-1", "note": "pre-op consult"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["patient_identifier"] == "MRN-SCHED-1"
    assert body["status"] == "scheduled"
    assert body["note"] == "pre-op consult"

    # Column holds ciphertext, never the plaintext.
    from sqlalchemy import select

    from app.core.models import ScheduleEntryModel

    row = (
        await db_session.execute(
            select(ScheduleEntryModel).where(
                ScheduleEntryModel.id == uuid.UUID(body["id"])
            )
        )
    ).scalar_one()
    assert row.patient_identifier_encrypted != b"MRN-SCHED-1"

    listed = await app_client.get(
        "/api/v1/me/schedule", headers=_bearer("CLINICIAN", clinician)
    )
    assert listed.status_code == 200
    ids = {e["patient_identifier"] for e in listed.json()}
    assert "MRN-SCHED-1" in ids


@pytest.mark.asyncio
async def test_list_is_scoped_to_owner(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Each clinician sees only their own entries — never the other's."""
    marie = await _seed_user(db_session)
    perry = await _seed_user(db_session)
    await db_session.commit()

    await app_client.post(
        "/api/v1/me/schedule",
        headers=_bearer("CLINICIAN", marie),
        json={"patient_identifier": "MRN-MARIE"},
    )
    await app_client.post(
        "/api/v1/me/schedule",
        headers=_bearer("CLINICIAN", perry),
        json={"patient_identifier": "MRN-PERRY"},
    )

    marie_list = (
        await app_client.get(
            "/api/v1/me/schedule", headers=_bearer("CLINICIAN", marie)
        )
    ).json()
    perry_list = (
        await app_client.get(
            "/api/v1/me/schedule", headers=_bearer("CLINICIAN", perry)
        )
    ).json()
    assert {e["patient_identifier"] for e in marie_list} == {"MRN-MARIE"}
    assert {e["patient_identifier"] for e in perry_list} == {"MRN-PERRY"}


@pytest.mark.asyncio
async def test_patch_and_delete_foreign_entry_returns_404(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A clinician cannot mutate or remove another clinician's entry — the
    row is invisible, so both return 404 (non-existence-leaking)."""
    owner = await _seed_user(db_session)
    intruder = await _seed_user(db_session)
    await db_session.commit()

    created = await app_client.post(
        "/api/v1/me/schedule",
        headers=_bearer("CLINICIAN", owner),
        json={"patient_identifier": "MRN-OWNED"},
    )
    entry_id = created.json()["id"]

    patched = await app_client.patch(
        f"/api/v1/me/schedule/{entry_id}",
        headers=_bearer("CLINICIAN", intruder),
        json={"status": "completed"},
    )
    assert patched.status_code == 404

    deleted = await app_client.delete(
        f"/api/v1/me/schedule/{entry_id}",
        headers=_bearer("CLINICIAN", intruder),
    )
    assert deleted.status_code == 404


@pytest.mark.asyncio
async def test_status_transitions_through_api(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Legal transition succeeds; re-opening a terminal status is 409."""
    clinician = await _seed_user(db_session)
    await db_session.commit()

    entry_id = (
        await app_client.post(
            "/api/v1/me/schedule",
            headers=_bearer("CLINICIAN", clinician),
            json={"patient_identifier": "MRN-FLOW"},
        )
    ).json()["id"]

    to_completed = await app_client.patch(
        f"/api/v1/me/schedule/{entry_id}",
        headers=_bearer("CLINICIAN", clinician),
        json={"status": "completed"},
    )
    assert to_completed.status_code == 200
    assert to_completed.json()["status"] == "completed"

    reopen = await app_client.patch(
        f"/api/v1/me/schedule/{entry_id}",
        headers=_bearer("CLINICIAN", clinician),
        json={"status": "scheduled"},
    )
    assert reopen.status_code == 409


@pytest.mark.asyncio
async def test_full_name_identifier_rejected_without_echo(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A pasted full name is 422 and the value never appears in the body."""
    clinician = await _seed_user(db_session)
    await db_session.commit()

    resp = await app_client.post(
        "/api/v1/me/schedule",
        headers=_bearer("CLINICIAN", clinician),
        json={"patient_identifier": "Jane Q Patient"},
    )
    assert resp.status_code == 422
    assert "Jane Q Patient" not in resp.text


@pytest.mark.asyncio
async def test_non_clinician_gets_403(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """/me/* is CLINICIAN-only — an ADMIN token is refused."""
    admin = await _seed_user(db_session, role=UserRole.ADMIN)
    await db_session.commit()

    resp = await app_client.get(
        "/api/v1/me/schedule", headers=_bearer("ADMIN", admin)
    )
    assert resp.status_code == 403
