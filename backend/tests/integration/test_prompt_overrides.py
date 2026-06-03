"""Integration tests for AI Prompts B — per-physician overlays
(AI-PROMPTS-B).

Covers the PATCH / DELETE surface that ``app/api/v1/me_prompts.py``
adds, plus the assembly module's per-physician isolation invariant.

DB strategy mirrors ``tests/e2e/conftest.py``:
  * A real Postgres is required — the per-physician isolation
    invariant is a SQL behaviour (UNIQUE constraint + owner_id
    column), and proving it via a real round-trip is the only way
    to catch a regression in the ORM mapping or migration.
  * Tests are skipped at collection if Postgres isn't reachable —
    same gate the e2e suite uses.
  * Each test runs inside an outer transaction + SAVEPOINT and is
    rolled back at teardown — zero residual rows between tests.

Test taxonomy
-------------
  * ``test_patch_happy_path`` — overlay stored, response shows
    ``is_overridden=True``, assembled_preview contains the separator
  * ``test_patch_banned_phrase_rejected`` — 400 with matched_phrase
    echoed back
  * ``test_patch_too_long_rejected`` / ``test_patch_empty_rejected``
  * ``test_delete_round_trip`` — DELETE removes the row, audit event
    written, follow-up GET shows base-only
  * ``test_one_physicians_overlay_does_not_leak`` — the CTO-locked
    per-physician scope invariant
  * ``test_audit_set_does_not_contain_overlay_text`` — PHI gate
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# Env vars before app import — APP_ENV=local enables the dev-token
# `<role>:<user_id>` bearer parser.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.audit_events import AuditEventType  # noqa: E402
from app.modules.prompts import (  # noqa: E402
    BANNED_PHRASES,
    OVERLAY_MAX_LENGTH,
    OVERLAY_SEPARATOR,
    PROMPTS,
    assemble_prompt,
)

# ── Postgres reachability gate (mirrors e2e conftest) ───────────────────────

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
    """Same probe the e2e conftest uses — TCP + auth."""
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
        return False, (
            f"asyncpg login as {_PG_USER}@{_PG_HOST}:{_PG_PORT}/{_PG_DB} "
            f"failed: {e}"
        )


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
    """Transactional session — outer transaction rolls back at teardown."""
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
    """ASGI client that yields the test's transactional session."""
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
def mock_audit_log(monkeypatch):
    """Replace AuditLogService with an AsyncMock so tests can assert on
    emitted events without touching DynamoDB."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    mock_service.get_session_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


async def _seed_clinician(db_session: AsyncSession) -> uuid.UUID:
    """Insert a CLINICIAN user row and return its id.

    Required because ``prompt_overrides.owner_id`` is a FK to
    ``users.id`` — a bare uuid4 would trip the foreign-key constraint
    on PATCH. Tests run in a SAVEPOINT that rolls back at teardown so
    these rows don't leak.
    """
    from app.core.models import UserModel
    from app.core.types import UserRole

    uid = uuid.uuid4()
    db_session.add(
        UserModel(
            id=uid,
            email=f"{uid}@aurion.test",
            password_hash="x",
            full_name="Test Clinician",
            role=UserRole.CLINICIAN,
        )
    )
    await db_session.flush()
    return uid


@pytest_asyncio.fixture
async def marie(
    db_session: AsyncSession,
) -> tuple[uuid.UUID, dict[str, str]]:
    """Marie — one of the two pilot physicians used in the isolation
    test. Real users row is seeded so the FK on prompt_overrides is
    satisfiable."""
    uid = await _seed_clinician(db_session)
    return uid, {"Authorization": f"Bearer CLINICIAN:{uid}"}


@pytest_asyncio.fixture
async def perry(
    db_session: AsyncSession,
) -> tuple[uuid.UUID, dict[str, str]]:
    """Perry — the other pilot physician used in the isolation test."""
    uid = await _seed_clinician(db_session)
    return uid, {"Authorization": f"Bearer CLINICIAN:{uid}"}


# ── PATCH happy path ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_happy_path(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    mock_audit_log: MagicMock,
) -> None:
    """Setting a valid overlay returns 200 + the updated PromptResponse;
    audit event is emitted with overlay_length but NOT the text."""
    _, headers = marie
    overlay = "Always note bilateral comparison when applicable."

    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": overlay},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["id"] == "note_generation"
    assert payload["overlay_text"] == overlay
    assert payload["is_overridden"] is True
    # assembled_preview contains the base text + separator + overlay.
    base = PROMPTS["note_generation"].system_prompt
    assert payload["assembled_preview"].startswith(base)
    assert OVERLAY_SEPARATOR in payload["assembled_preview"]
    assert overlay in payload["assembled_preview"]

    # Audit emitted with the locked kwargs only.
    mock_audit_log.write_event.assert_called()
    call = mock_audit_log.write_event.call_args
    assert call.kwargs["event_type"] is AuditEventType.PROMPT_OVERRIDE_SET
    assert call.kwargs["prompt_id"] == "note_generation"
    assert call.kwargs["overlay_length"] == len(overlay)


@pytest.mark.asyncio
async def test_patch_idempotent_upsert(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Calling PATCH twice with different text upserts — single row,
    last write wins. UNIQUE (owner_id, prompt_id) is the invariant."""
    _, headers = marie
    first = "Use millimeters not centimeters for wound measurements."
    second = "Prefer 'observed' over 'noted' in physical exam claims."

    r1 = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": first},
    )
    assert r1.status_code == 200
    r2 = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": second},
    )
    assert r2.status_code == 200
    assert r2.json()["overlay_text"] == second


# ── PATCH safety failures ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("banned", BANNED_PHRASES)
async def test_patch_banned_phrase_rejected(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    banned: str,
) -> None:
    """Every banlist entry triggers a 400 with matched_phrase echoed
    back. The echo is the banned phrase itself — never patient
    content — so it's safe to surface to the physician."""
    _, headers = marie
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": f"Hey: {banned}, please."},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "banned_phrase"
    assert detail["matched_phrase"] == banned


@pytest.mark.asyncio
async def test_patch_too_long_rejected(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    over = "a" * (OVERLAY_MAX_LENGTH + 1)
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": over},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "too_long"


@pytest.mark.asyncio
async def test_patch_empty_rejected(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": "   "},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "empty"


@pytest.mark.asyncio
async def test_patch_unknown_prompt_id_404(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    r = await app_client.patch(
        "/api/v1/me/prompts/not_a_prompt",
        headers=headers,
        json={"overlay_text": "anything"},
    )
    assert r.status_code == 404


# ── DELETE round-trip ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_round_trip(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    mock_audit_log: MagicMock,
) -> None:
    """Set overlay → DELETE → response is base-only → audit emits
    PROMPT_OVERRIDE_CLEARED."""
    _, headers = marie
    overlay = "Always note bilateral comparison when applicable."
    await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": overlay},
    )
    r = await app_client.delete(
        "/api/v1/me/prompts/note_generation", headers=headers
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["overlay_text"] is None
    assert payload["is_overridden"] is False
    assert (
        payload["assembled_preview"] == PROMPTS["note_generation"].system_prompt
    )

    # Latest call is the CLEARED event.
    last = mock_audit_log.write_event.call_args
    assert last.kwargs["event_type"] is AuditEventType.PROMPT_OVERRIDE_CLEARED


@pytest.mark.asyncio
async def test_delete_no_existing_overlay_is_idempotent(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Deleting when no overlay exists still returns 200 with the base."""
    _, headers = marie
    r = await app_client.delete(
        "/api/v1/me/prompts/note_generation", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["overlay_text"] is None


# ── PHI gate: audit detail does NOT carry overlay text ──────────────────────


@pytest.mark.asyncio
async def test_audit_set_does_not_contain_overlay_text(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    mock_audit_log: MagicMock,
) -> None:
    """The overlay text is the physician's personal phrasing — never
    in the audit row. Only ``overlay_length`` makes the trail."""
    _, headers = marie
    overlay = (
        "A distinctive sentinel string the audit row must NEVER contain: "
        "SECRET_SENTINEL_TOKEN_42"
    )
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": overlay},
    )
    assert r.status_code == 200

    # Inspect every recorded audit call. None of them should carry the
    # overlay text in any kwarg.
    for call in mock_audit_log.write_event.call_args_list:
        kwargs_str = repr(call.kwargs)
        assert "SECRET_SENTINEL_TOKEN_42" not in kwargs_str, (
            "overlay text must never appear in an audit row"
        )


# ── Per-physician isolation (CTO-locked architectural rule) ────────────────


@pytest.mark.asyncio
async def test_one_physicians_overlay_does_not_leak(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
    perry: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Marie sets an overlay on ``note_generation``. The assembled
    prompt for Perry on the same prompt_id is base-only — Marie's
    text does not appear.

    This is the architectural invariant locked by the CTO in the
    Phase B brief: "Marie's overlays affect only sessions where she
    is clinician_id. Perry's overlays affect only Perry's. No
    clinic-wide overrides."
    """
    marie_id, marie_headers = marie
    perry_id, _perry_headers = perry
    overlay = "MARIE_PRIVATE_OVERLAY_TEXT — should never reach Perry"

    # Marie saves an overlay via the API.
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=marie_headers,
        json={"overlay_text": overlay},
    )
    assert r.status_code == 200

    # Marie's assembled prompt contains the overlay.
    marie_assembled = await assemble_prompt(
        "note_generation", marie_id, db_session
    )
    assert overlay in marie_assembled, (
        "Marie's own assembled prompt must contain her overlay"
    )

    # Perry's assembled prompt is the base, unchanged. Critical: this
    # is the invariant — Marie's text MUST NOT appear in Perry's
    # assembled prompt.
    perry_assembled = await assemble_prompt(
        "note_generation", perry_id, db_session
    )
    assert overlay not in perry_assembled
    assert perry_assembled == PROMPTS["note_generation"].system_prompt


# ── Base immutability (echo of unit test against the real DB) ──────────────


@pytest.mark.asyncio
async def test_assemble_prompt_preserves_base_through_db(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """The base text appears verbatim at the start of the assembled
    prompt — even after a round-trip through SQL. Guards against an
    ORM mapping bug that could silently trim or transform the text."""
    marie_id, marie_headers = marie
    overlay = "Use clinical-neutral phrasing where possible."
    await app_client.patch(
        "/api/v1/me/prompts/vision_frame",
        headers=marie_headers,
        json={"overlay_text": overlay},
    )
    assembled = await assemble_prompt(
        "vision_frame", marie_id, db_session
    )
    base = PROMPTS["vision_frame"].system_prompt
    assert assembled.startswith(base)
    assert assembled.endswith(overlay)


# ── Role gate: non-CLINICIAN can't PATCH/DELETE ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "EVAL_TEAM", "COMPLIANCE_OFFICER"])
async def test_patch_blocked_for_non_clinician_roles(
    app_client: AsyncClient,
    role: str,
) -> None:
    """Overlays are personal physician preferences — admins must not
    edit them on a physician's behalf."""
    headers = {"Authorization": f"Bearer {role}:{uuid.uuid4()}"}
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"overlay_text": "anything"},
    )
    assert r.status_code == 403


# ── Forward link: row exists in the table after PATCH ──────────────────────


@pytest.mark.asyncio
async def test_patch_persists_row_to_table(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Belt-and-braces: PATCH writes a row visible via the ORM in the
    same transactional session. Cheap regression catch if the route
    ever skips the commit / flush."""
    from app.core.models import PromptOverrideModel

    marie_id, marie_headers = marie
    overlay = "Document the patient's preferred name in the chief complaint."
    await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=marie_headers,
        json={"overlay_text": overlay},
    )
    stmt = select(PromptOverrideModel).where(
        PromptOverrideModel.owner_id == marie_id,
        PromptOverrideModel.prompt_id == "note_generation",
    )
    result = await db_session.execute(stmt)
    row = result.scalar_one()
    assert row.overlay_text == overlay
