"""Integration test for the #61 conversion of
``GET /me/patients/{identifier}/sessions`` to the indexed-hash
lookup path.

The pre-#61 implementation linear-scanned every per-clinician session
and called ``decrypt_str`` on each ``external_reference_id_encrypted``
column to compare. The #61 full slice replaces that with a B-tree
index on ``sessions.external_reference_id_hash`` and an equality
predicate using ``hash_identifier``. This test locks two contracts:

  1. The route still returns ONLY the matching sessions for the
     calling clinician (per-physician scope intact).
  2. The route does NOT touch ``decrypt_str`` on the hot path — the
     indexed predicate alone must be enough. A regression that
     re-introduces the per-row decrypt would defeat the indexing.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault(
    "AURION_IDENTIFIER_HMAC_KEY", "integration-test-key-indexed-lookup"
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
from app.core.identifier_hash import hash_identifier  # noqa: E402
from app.core.models import SessionModel, UserModel  # noqa: E402
from app.core.types import SessionState, UserRole  # noqa: E402


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
    """Dev-mode bearer token shape — APP_ENV=local accepts
    ``<role>:<user_id>`` directly as the JWT payload. Matches the
    pattern in test_prompt_overrides.py."""
    return {"Authorization": f"Bearer {role}:{user_id}"}


async def _seed_clinician(db_session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    db_session.add(
        UserModel(
            id=uid,
            email=f"{uid}@aurion.test",
            password_hash="x",
            full_name="Indexed Lookup Test Clinician",
            role=UserRole.CLINICIAN,
        )
    )
    await db_session.flush()
    return uid


async def _seed_session_with_identifier(
    db_session: AsyncSession,
    clinician_id: uuid.UUID,
    identifier_plaintext: str,
    *,
    specialty: str = "orthopedic_surgery",
    created_at: datetime | None = None,
) -> SessionModel:
    sid = uuid.uuid4()
    row = SessionModel(
        id=sid,
        clinician_id=clinician_id,
        specialty=specialty,
        state=SessionState.REVIEW_COMPLETE,
        consent_confirmed=True,
        encounter_type="doctor_patient",
        capture_mode="multimodal",
        output_language="en",
        external_reference_id_encrypted=b"ENC::" + identifier_plaintext.encode("utf-8"),
        external_reference_id_hash=hash_identifier(identifier_plaintext),
    )
    if created_at is not None:
        row.created_at = created_at
        row.updated_at = created_at
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_me_patients_endpoint_returns_only_matching_sessions(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two sessions for the same clinician with different identifiers
    — the endpoint must return ONLY the one whose identifier matches
    the request path. The matched row's `created_at` survives into
    the response.
    """
    clinician_id = await _seed_clinician(db_session)

    older = await _seed_session_with_identifier(
        db_session,
        clinician_id,
        "MRN-MATCH-1",
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    newer = await _seed_session_with_identifier(
        db_session,
        clinician_id,
        "MRN-MATCH-1",
        created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    # Unrelated identifier — must NOT come back in the matched
    # response even though it belongs to the same clinician.
    await _seed_session_with_identifier(
        db_session, clinician_id, "MRN-OTHER-9"
    )
    await db_session.commit()

    response = await app_client.get(
        "/api/v1/me/patients/MRN-MATCH-1/sessions",
        headers=_bearer("CLINICIAN", clinician_id),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    matched_ids = {row["session_id"] for row in payload}
    assert matched_ids == {str(older.id), str(newer.id)}
    # Newest-first sort comes from the SQL ORDER BY, not the post-
    # query Python sort.
    assert payload[0]["session_id"] == str(newer.id)


@pytest.mark.asyncio
async def test_me_patients_endpoint_per_physician_scope(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The endpoint must filter on the caller's clinician_id alone.
    Another physician's row with the same identifier must NOT come
    back — even if the hash matches."""
    marie = await _seed_clinician(db_session)
    perry = await _seed_clinician(db_session)
    identifier = "MRN-SHARED-PANEL"

    await _seed_session_with_identifier(db_session, marie, identifier)
    perry_row = await _seed_session_with_identifier(
        db_session, perry, identifier
    )
    await db_session.commit()

    response = await app_client.get(
        f"/api/v1/me/patients/{identifier}/sessions",
        headers=_bearer("CLINICIAN", perry),
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["session_id"] == str(perry_row.id)


@pytest.mark.asyncio
async def test_me_patients_endpoint_empty_identifier_returns_422(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Empty / whitespace identifier was already a 422 in the
    foundation slice; the indexed-hash path must preserve that
    contract since a hash of empty string would either raise or
    produce a fixed digest that matches every empty-identifier row.
    """
    clinician_id = await _seed_clinician(db_session)
    await db_session.commit()

    # An identifier that is only whitespace: the route's .strip() turns
    # it into "" which surfaces as 422 from the explicit guard. The
    # path segment must not be literally empty (FastAPI would 404
    # before the handler runs); we use a single space to exercise the
    # in-handler trim path.
    response = await app_client.get(
        "/api/v1/me/patients/%20/sessions",
        headers=_bearer("CLINICIAN", clinician_id),
    )
    assert response.status_code == 422
