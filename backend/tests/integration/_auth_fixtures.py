"""Shared fixtures for the AUTH-PIVOT-BACKEND integration tests.

The auth router writes to ``users``, ``refresh_tokens``,
``password_reset_tokens``, and reads/writes to KMS via
``encrypt_str``/``decrypt_str``. Real Postgres is required (per-test
transactional rollback isolates rows); KMS is mocked at the
``kms_encryption`` boundary because LocalStack KMS adds 200ms+ per
encrypt that would slow the suite without buying coverage we don't
already have.

Mirror of the conftest pattern in
``tests/integration/test_prompt_overrides.py``:
  * Real Postgres → tests skip if not reachable.
  * Per-test SAVEPOINT + outer rollback → zero residual rows.
  * Audit log mocked → no DynamoDB dependency.
  * KMS mocked → no encrypt/decrypt latency.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Env vars BEFORE app import.
os.environ.setdefault("APP_ENV", "production")  # exercise the prod JWT path
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault(
    "AUTH_JWT_SIGNING_KEY",
    "auth-pivot-test-signing-key-do-not-use-in-prod-32-bytes-min",
)
os.environ.setdefault("AUTH_EMAIL_ENABLED", "false")  # log-only

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.types import UserRole  # noqa: E402
from app.modules.auth.passwords import hash_password  # noqa: E402

# ── Postgres reachability gate ─────────────────────────────────────────────

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
    """TCP + asyncpg login probe. Same pattern the e2e conftest uses."""
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


PG_OK, PG_SKIP_REASON = _pg_reachable()

skip_if_no_pg = pytest.mark.skipif(
    not PG_OK,
    reason=(
        "Aurion Postgres not available — start "
        "`docker compose up -d postgres`. "
        f"({PG_SKIP_REASON})"
    ),
)


# ── DB fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Transactional session — outer txn rolled back at teardown."""
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
    """ASGI client wired to the test transaction."""
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


# ── Audit log + KMS mocks ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_audit_log(monkeypatch):
    """Replace AuditLogService with an AsyncMock so tests can assert on
    emitted events without touching DynamoDB."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    mock_service.get_session_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


@pytest.fixture(autouse=True)
def mock_kms(monkeypatch):
    """Stub KMS encrypt/decrypt — round-trip preserves the plaintext as
    UTF-8 prefixed with a sentinel so decrypt can sanity-check it.

    No round trip to LocalStack KMS. The TOTP secret-handling logic is
    what we want to cover; encrypt/decrypt themselves are trivial.
    """

    def fake_encrypt(plaintext: str, key_id=None) -> bytes:
        return b"kmsfake:" + plaintext.encode("utf-8")

    def fake_decrypt(ciphertext: bytes) -> str:
        assert ciphertext.startswith(b"kmsfake:"), ciphertext
        return ciphertext[len(b"kmsfake:"):].decode("utf-8")

    # Patch at all import sites. The auth router pulls them through
    # `from app.core.kms_encryption import decrypt_str, encrypt_str`,
    # so patching the kms_encryption module covers both usages.
    monkeypatch.setattr(
        "app.core.kms_encryption.encrypt_str", fake_encrypt
    )
    monkeypatch.setattr(
        "app.core.kms_encryption.decrypt_str", fake_decrypt
    )
    monkeypatch.setattr(
        "app.api.v1.auth.encrypt_str", fake_encrypt
    )
    monkeypatch.setattr(
        "app.api.v1.auth.decrypt_str", fake_decrypt
    )


# ── User seeding helpers ────────────────────────────────────────────────────


CLINICIAN_EMAIL = "clinician.auth@test.local"
CLINICIAN_PASSWORD = "Sup3rSecret!"
ADMIN_EMAIL = "admin.auth@test.local"
ADMIN_PASSWORD = "Adm1nSecret!"


async def seed_user(
    db: AsyncSession,
    *,
    email: str = CLINICIAN_EMAIL,
    password: str = CLINICIAN_PASSWORD,
    role: UserRole = UserRole.CLINICIAN,
    is_active: bool = True,
) -> tuple[uuid.UUID, str]:
    """Insert a fresh user row + return its uuid + the raw password.

    Generates a unique email per call (suffixed with a short random
    string) so two tests using ``CLINICIAN_EMAIL`` in parallel don't
    collide. The raw password is returned so the test can build the
    login body without re-implementing the seed.
    """
    from app.core.models import UserModel

    unique_email = f"{email.split('@')[0]}.{uuid.uuid4().hex[:6]}@test.local"
    user = UserModel(
        email=unique_email,
        password_hash=hash_password(password),
        full_name=f"Test {role.value}",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user.id, unique_email


def sha256(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()
