"""Integration tests for PS-02 — admin-published prompts take effect
(Prompt Studio, part of MVP #524).

Proves, through a real Postgres round-trip, that ``assemble_prompt`` resolves in
the documented order: personal override → active publication (SELF → ROLE →
ALL) → registry default. The precedence rule itself is unit-tested in
``tests/unit/test_prompt_resolution_precedence.py``; here we prove the SQL query
+ ORM wiring that feeds it.

DB strategy mirrors ``tests/integration/test_prompt_overrides.py``: a real
Postgres is required (skipped at collection if unreachable); each test runs in
an outer transaction + SAVEPOINT rolled back at teardown.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import AsyncGenerator, Optional

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.types import PublicationScope, UserRole  # noqa: E402
from app.modules.prompts import PROMPTS, assemble_prompt  # noqa: E402

_JOB = "note_generation"

# ── Postgres reachability gate (mirrors test_prompt_overrides) ──────────────

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


async def _seed_user(db: AsyncSession, role: UserRole) -> uuid.UUID:
    """Insert a user row and return its id (FKs on publications/overrides
    point at users.id). Rolled back at teardown."""
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


async def _seed_publication(
    db: AsyncSession,
    *,
    text: str,
    scope: PublicationScope,
    job_id: str = _JOB,
    target_user_id: Optional[uuid.UUID] = None,
    target_role: Optional[str] = None,
) -> None:
    """Create a studio prompt + v1 + an active publication for ``job_id``."""
    from app.core.models import (
        PromptPublicationModel,
        StudioPromptModel,
        StudioPromptVersionModel,
    )

    sp = StudioPromptModel(id=uuid.uuid4(), job_id=job_id, name="test prompt")
    db.add(sp)
    await db.flush()
    ver = StudioPromptVersionModel(
        id=uuid.uuid4(), studio_prompt_id=sp.id, version_no=1, text=text
    )
    db.add(ver)
    await db.flush()
    db.add(
        PromptPublicationModel(
            id=uuid.uuid4(),
            job_id=job_id,
            version_id=ver.id,
            scope=scope.value,
            target_user_id=target_user_id,
            target_role=target_role,
        )
    )
    await db.flush()


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_published_all_takes_effect(db_session: AsyncSession) -> None:
    """A clinician with no override receives the ALL-published text."""
    clinician = await _seed_user(db_session, UserRole.CLINICIAN)
    await _seed_publication(db_session, text="SHARED_TO_ALL", scope=PublicationScope.ALL)

    assert await assemble_prompt(_JOB, clinician, db_session) == "SHARED_TO_ALL"


@pytest.mark.asyncio
async def test_personal_override_beats_publication(db_session: AsyncSession) -> None:
    """A physician's own saved prompt outranks an admin publication."""
    from app.core.models import PromptOverrideModel

    clinician = await _seed_user(db_session, UserRole.CLINICIAN)
    await _seed_publication(db_session, text="SHARED_TO_ALL", scope=PublicationScope.ALL)
    db_session.add(
        PromptOverrideModel(
            id=uuid.uuid4(),
            owner_id=clinician,
            prompt_id=_JOB,
            user_prompt_text="OVERRIDE_WINS",
        )
    )
    await db_session.flush()

    assert await assemble_prompt(_JOB, clinician, db_session) == "OVERRIDE_WINS"


@pytest.mark.asyncio
async def test_self_publication_targets_only_owner(db_session: AsyncSession) -> None:
    """A SELF publication reaches its target; another clinician falls to the
    registry default."""
    target = await _seed_user(db_session, UserRole.CLINICIAN)
    other = await _seed_user(db_session, UserRole.CLINICIAN)
    await _seed_publication(
        db_session, text="JUST_ME", scope=PublicationScope.SELF, target_user_id=target
    )

    assert await assemble_prompt(_JOB, target, db_session) == "JUST_ME"
    assert (
        await assemble_prompt(_JOB, other, db_session)
        == PROMPTS[_JOB].system_prompt
    )


@pytest.mark.asyncio
async def test_role_publication_targets_only_that_role(db_session: AsyncSession) -> None:
    """A ROLE publication reaches users of that role only."""
    clinician = await _seed_user(db_session, UserRole.CLINICIAN)
    admin = await _seed_user(db_session, UserRole.ADMIN)
    await _seed_publication(
        db_session,
        text="FOR_CLINICIANS",
        scope=PublicationScope.ROLE,
        target_role=UserRole.CLINICIAN.value,
    )

    assert await assemble_prompt(_JOB, clinician, db_session) == "FOR_CLINICIANS"
    assert (
        await assemble_prompt(_JOB, admin, db_session) == PROMPTS[_JOB].system_prompt
    )


@pytest.mark.asyncio
async def test_registry_default_when_nothing_published(db_session: AsyncSession) -> None:
    """No override and no publication → the in-code registry default."""
    clinician = await _seed_user(db_session, UserRole.CLINICIAN)
    assert (
        await assemble_prompt(_JOB, clinician, db_session) == PROMPTS[_JOB].system_prompt
    )
