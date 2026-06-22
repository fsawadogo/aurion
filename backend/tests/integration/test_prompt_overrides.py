"""Integration tests for AI Prompts B — per-physician REPLACEMENT
user prompts (AI-PROMPTS-B).

Covers the PATCH / DELETE surface that ``app/api/v1/me_prompts.py``
adds, plus the selection module's per-physician isolation invariant
under replacement semantics.

DB strategy mirrors ``tests/e2e/conftest.py``:
  * A real Postgres is required — the per-physician isolation
    invariant is a SQL behaviour (UNIQUE constraint + owner_id
    column), and proving it via a real round-trip is the only way
    to catch a regression in the ORM mapping or migration.
  * Tests are skipped at collection if Postgres isn't reachable —
    same gate the e2e suite uses.
  * Each test runs inside an outer transaction + SAVEPOINT and is
    rolled back at teardown — zero residual rows between tests.

Test taxonomy (refactored from PR #227 v1 to replacement semantics):
  * ``test_patch_happy_path`` — user prompt stored, response shows
    ``is_overridden=True``, active_prompt == user_prompt_text
    (NOT base + user_prompt_text)
  * ``test_patch_banned_phrase_rejected`` — 400 with matched_phrase
    echoed back
  * ``test_patch_missing_anchor_*`` — NEW under replacement: the
    saved prompt must include descriptive-mode anchor language
  * ``test_patch_too_long_rejected`` (5000 cap, raised from 1000)
  * ``test_patch_empty_rejected``
  * ``test_delete_round_trip`` — DELETE removes the row, audit event
    written, follow-up GET shows system default
  * ``test_one_physicians_user_prompt_does_not_leak`` — the CTO-
    locked per-physician scope invariant, now stronger: Marie's
    saved prompt does not appear in Perry's active_prompt — and
    Perry's active_prompt is the system default, not the default
    plus Marie's text
  * ``test_audit_set_does_not_contain_user_prompt_text`` — PHI gate
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
    PROMPTS,
    USER_PROMPT_MAX_LENGTH,
    assemble_prompt,
)

# A clinical-documentation prompt that contains BOTH required anchor
# groups + no banned phrases. Used by every "happy path" test so a
# synonyms tweak ripples in one place.
_WELL_FORMED_USER_PROMPT = (
    "You are a clinical documentation assistant. "
    "Describe only what was directly captured during the encounter. "
    "Document the patient's complaints and any observed physical "
    "findings. Do not interpret findings, do not diagnose, and do "
    "not infer clinical meaning."
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
    """Setting a valid user prompt returns 200 + the updated
    PromptResponse; audit event is emitted with user_prompt_length
    but NOT the text. ``active_prompt`` equals the user prompt
    verbatim — the registry default is NOT concatenated below."""
    _, headers = marie

    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": _WELL_FORMED_USER_PROMPT},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["id"] == "note_generation"
    assert payload["user_prompt_text"] == _WELL_FORMED_USER_PROMPT
    assert payload["is_overridden"] is True
    assert payload["system_prompt_is_fallback"] is True
    # active_prompt is the user prompt VERBATIM — replacement, not
    # concatenation. The registry default is NOT under it.
    assert payload["active_prompt"] == _WELL_FORMED_USER_PROMPT
    base = PROMPTS["note_generation"].system_prompt
    assert base not in payload["active_prompt"], (
        "Replacement semantics violated — registry default was "
        "concatenated under the user prompt"
    )

    # Audit emitted with the locked kwargs only.
    mock_audit_log.write_event.assert_called()
    call = mock_audit_log.write_event.call_args
    assert call.kwargs["event_type"] is AuditEventType.PROMPT_USER_PROMPT_SET
    assert call.kwargs["prompt_id"] == "note_generation"
    assert call.kwargs["user_prompt_length"] == len(_WELL_FORMED_USER_PROMPT)


@pytest.mark.asyncio
async def test_patch_idempotent_upsert(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Calling PATCH twice with different text upserts — single row,
    last write wins. UNIQUE (owner_id, prompt_id) is the invariant.

    Both payloads must satisfy the validator (anchor + no banlist) so
    each one would independently save.
    """
    _, headers = marie
    first = _WELL_FORMED_USER_PROMPT
    second = (
        "Describe only what is captured. Document the patient's "
        "stated concerns. Do not interpret or diagnose."
    )

    r1 = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": first},
    )
    assert r1.status_code == 200, r1.text
    r2 = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": second},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["user_prompt_text"] == second
    assert r2.json()["active_prompt"] == second


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
    poisoned = _WELL_FORMED_USER_PROMPT + f" Also: {banned}, please."
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": poisoned},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "banned_phrase"
    assert detail["matched_phrase"] == banned


@pytest.mark.asyncio
async def test_save_rejects_prompt_with_diagnose_the_patient_banned_phrase(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Targeted regression for the diagnose-the-patient banlist entry
    on the API surface (echoes the unit test against the HTTP layer)."""
    _, headers = marie
    poisoned = _WELL_FORMED_USER_PROMPT + " Then diagnose the patient."
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": poisoned},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "banned_phrase"
    assert detail["matched_phrase"] == "diagnose the patient"


@pytest.mark.asyncio
async def test_save_rejects_prompt_over_5000_chars(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """The 5000-char cap is enforced at the API boundary."""
    _, headers = marie
    over = "a" * (USER_PROMPT_MAX_LENGTH + 1)
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": over},
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
        json={"user_prompt_text": "   "},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "empty"


@pytest.mark.asyncio
async def test_save_rejects_prompt_without_descriptive_anchor_descriptive(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """NEW under replacement semantics: a prompt missing the
    "describe / document / record / report what" descriptive intent
    fails with code missing_descriptive_anchor + group index 0."""
    _, headers = marie
    missing_describe = (
        "You are a clinical assistant. Do not interpret, do not "
        "diagnose, and do not infer clinical meaning."
    )
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": missing_describe},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "missing_descriptive_anchor"
    assert detail["missing_anchor_group"] == 0


@pytest.mark.asyncio
async def test_save_rejects_prompt_without_descriptive_anchor_no_interpret(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """NEW under replacement semantics: a prompt missing the
    "do not interpret / diagnose / infer" instruction fails with code
    missing_descriptive_anchor + group index 1."""
    _, headers = marie
    missing_no_interpret = (
        "You are a clinical assistant. Describe what was captured. "
        "Document complaints. Record visible equipment positions."
    )
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": missing_no_interpret},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "missing_descriptive_anchor"
    assert detail["missing_anchor_group"] == 1


@pytest.mark.asyncio
async def test_save_accepts_well_formed_full_prompt(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """The canonical well-formed prompt is accepted by the API. Echo
    of the unit test against the HTTP layer."""
    _, headers = marie
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": _WELL_FORMED_USER_PROMPT},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_overridden"] is True


@pytest.mark.asyncio
async def test_patch_unknown_prompt_id_404(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    r = await app_client.patch(
        "/api/v1/me/prompts/not_a_prompt",
        headers=headers,
        json={"user_prompt_text": _WELL_FORMED_USER_PROMPT},
    )
    assert r.status_code == 404


# ── DELETE round-trip ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_round_trip(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    mock_audit_log: MagicMock,
) -> None:
    """Set user prompt → DELETE → response shows system default →
    audit emits PROMPT_USER_PROMPT_CLEARED."""
    _, headers = marie
    await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": _WELL_FORMED_USER_PROMPT},
    )
    r = await app_client.delete(
        "/api/v1/me/prompts/note_generation", headers=headers
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["user_prompt_text"] is None
    assert payload["is_overridden"] is False
    assert payload["active_prompt"] == PROMPTS["note_generation"].system_prompt

    # Latest call is the CLEARED event.
    last = mock_audit_log.write_event.call_args
    assert (
        last.kwargs["event_type"] is AuditEventType.PROMPT_USER_PROMPT_CLEARED
    )


@pytest.mark.asyncio
async def test_delete_no_existing_user_prompt_is_idempotent(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Deleting when no user prompt exists still returns 200 with the
    system default."""
    _, headers = marie
    r = await app_client.delete(
        "/api/v1/me/prompts/note_generation", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["user_prompt_text"] is None


# ── PHI gate: audit detail does NOT carry user prompt text ─────────────────


@pytest.mark.asyncio
async def test_audit_set_does_not_contain_user_prompt_text(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    mock_audit_log: MagicMock,
) -> None:
    """The user prompt text is the physician's personal phrasing —
    never in the audit row. Only ``user_prompt_length`` makes the
    trail."""
    _, headers = marie
    sentinel = "SECRET_SENTINEL_TOKEN_42"
    prompt_with_sentinel = (
        _WELL_FORMED_USER_PROMPT
        + f" Distinctive marker the audit row must NEVER contain: {sentinel}"
    )
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": prompt_with_sentinel},
    )
    assert r.status_code == 200, r.text

    # Inspect every recorded audit call. None should carry the user
    # prompt text in any kwarg.
    for call in mock_audit_log.write_event.call_args_list:
        kwargs_str = repr(call.kwargs)
        assert sentinel not in kwargs_str, (
            "user prompt text must never appear in an audit row"
        )


# ── Per-physician isolation (CTO-locked architectural rule) ────────────────


@pytest.mark.asyncio
async def test_one_physicians_user_prompt_does_not_leak(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
    perry: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Marie saves a user prompt on ``note_generation``. The assembled
    prompt for Perry on the same prompt_id is the SYSTEM DEFAULT —
    Marie's text does not appear, AND the system default is what Perry
    gets (not "default + Marie's text", which would be the old append-
    only behaviour).

    This is the architectural invariant locked by the CTO in the
    Phase B brief: "Marie's user prompts affect only sessions where
    she is clinician_id. Perry's user prompts affect only Perry's.
    No clinic-wide overrides."
    """
    marie_id, marie_headers = marie
    perry_id, _perry_headers = perry
    # Marie's saved prompt embeds a distinctive sentinel so we can
    # assert its absence from Perry's selected prompt.
    marie_prompt = (
        _WELL_FORMED_USER_PROMPT
        + " MARIE_PRIVATE_PROMPT_TEXT — should never reach Perry."
    )

    # Marie saves her user prompt via the API.
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=marie_headers,
        json={"user_prompt_text": marie_prompt},
    )
    assert r.status_code == 200, r.text

    # Marie's selected prompt is her saved text alone — replacement.
    marie_selected = await assemble_prompt(
        "note_generation", marie_id, db_session
    )
    assert marie_selected == marie_prompt, (
        "Marie's selected prompt should be her saved text verbatim "
        "(replacement semantics)"
    )

    # Perry's selected prompt is the SYSTEM DEFAULT — Marie's text MUST
    # NOT appear AND the base default is exactly what Perry receives.
    perry_selected = await assemble_prompt(
        "note_generation", perry_id, db_session
    )
    assert "MARIE_PRIVATE_PROMPT_TEXT" not in perry_selected
    assert perry_selected == PROMPTS["note_generation"].system_prompt, (
        "Perry's selected prompt must be the system default — not "
        "Marie's text, not default + Marie's text"
    )


# ── Replacement invariant — through the real DB ─────────────────────────────


@pytest.mark.asyncio
async def test_user_prompt_replaces_system_through_db(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """The selected prompt is EXACTLY the user prompt text — verbatim
    — even after a round-trip through SQL. Guards against an ORM
    mapping bug that could silently trim or transform the text, and
    against a regression that reintroduces concatenation.
    """
    marie_id, marie_headers = marie
    user_prompt = _WELL_FORMED_USER_PROMPT
    await app_client.patch(
        "/api/v1/me/prompts/vision_frame",
        headers=marie_headers,
        json={"user_prompt_text": user_prompt},
    )
    selected = await assemble_prompt("vision_frame", marie_id, db_session)
    assert selected == user_prompt, (
        "Replacement semantics broken: selected prompt is not the user "
        "prompt verbatim"
    )
    base = PROMPTS["vision_frame"].system_prompt
    assert base not in selected, (
        "Replacement semantics broken: the registry default was "
        "concatenated under the user prompt"
    )


@pytest.mark.asyncio
async def test_system_prompt_used_when_no_user_prompt_through_db(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """When the physician has not saved a user prompt for this
    prompt_id, the selected prompt is the registry default — the
    fallback path. Run through a real DB to catch any incorrect
    LEFT JOIN / NULL handling in the lookup query.
    """
    marie_id, _ = marie
    selected = await assemble_prompt("vision_frame", marie_id, db_session)
    assert selected == PROMPTS["vision_frame"].system_prompt


# ── Role gate: non-CLINICIAN can't PATCH/DELETE ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "EVAL_TEAM", "COMPLIANCE_OFFICER"])
async def test_patch_blocked_for_non_clinician_roles(
    app_client: AsyncClient,
    role: str,
) -> None:
    """User prompts are personal physician config — admins must not
    edit them on a physician's behalf."""
    headers = {"Authorization": f"Bearer {role}:{uuid.uuid4()}"}
    r = await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=headers,
        json={"user_prompt_text": _WELL_FORMED_USER_PROMPT},
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
    same transactional session, with the renamed column populated.
    Cheap regression catch if the route ever skips the commit / flush
    or the model field rename misses a code path."""
    from app.core.models import PromptOverrideModel

    marie_id, marie_headers = marie
    await app_client.patch(
        "/api/v1/me/prompts/note_generation",
        headers=marie_headers,
        json={"user_prompt_text": _WELL_FORMED_USER_PROMPT},
    )
    stmt = select(PromptOverrideModel).where(
        PromptOverrideModel.owner_id == marie_id,
        PromptOverrideModel.prompt_id == "note_generation",
    )
    result = await db_session.execute(stmt)
    row = result.scalar_one()
    assert row.user_prompt_text == _WELL_FORMED_USER_PROMPT


# ── Specialty STYLE guidance overrides (PATCH/DELETE /me/prompts/specialties) ─
#
# Same per-physician override machinery (prompt_overrides table) reused under
# the ``specialty_style:`` namespace. Additive layer — validated by the
# banlist + length but NOT the descriptive-anchor gate (the base system prompt
# keeps the descriptive-mode boundary).

_SPECIALTY = "orthopedic_surgery"
_SPECIALTY_URL = f"/api/v1/me/prompts/specialties/{_SPECIALTY}"
_WELL_FORMED_GUIDANCE = (
    "Lead with the chief complaint. Capture range of motion in degrees and "
    "strength on the 0-5 scale exactly as the physician states them."
)


@pytest.mark.asyncio
async def test_patch_specialty_guidance_happy_path(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    mock_audit_log: MagicMock,
) -> None:
    _, headers = marie
    r = await app_client.patch(
        _SPECIALTY_URL, headers=headers, json={"guidance": _WELL_FORMED_GUIDANCE}
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["key"] == _SPECIALTY
    assert payload["user_guidance"] == _WELL_FORMED_GUIDANCE
    assert payload["is_overridden"] is True
    assert payload["active_guidance"] == _WELL_FORMED_GUIDANCE
    # The shipped default is still surfaced for the "default" preview pane.
    assert payload["guidance"] and payload["guidance"] != _WELL_FORMED_GUIDANCE

    # Audit emitted with the NAMESPACED prompt_id + length only (no text).
    call = mock_audit_log.write_event.call_args
    assert call.kwargs["event_type"] is AuditEventType.PROMPT_USER_PROMPT_SET
    assert call.kwargs["prompt_id"] == f"specialty_style:{_SPECIALTY}"
    assert call.kwargs["user_prompt_length"] == len(_WELL_FORMED_GUIDANCE)


@pytest.mark.asyncio
async def test_patch_specialty_guidance_additive_no_anchor_required(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """A pure style pointer with NO descriptive-mode anchor language is
    accepted — the additive layer doesn't need it (unlike the replacement
    registry override)."""
    _, headers = marie
    r = await app_client.patch(
        _SPECIALTY_URL,
        headers=headers,
        json={"guidance": "Lead with vital signs; capture each value as stated."},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_patch_specialty_guidance_banlist_rejected(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    r = await app_client.patch(
        _SPECIALTY_URL,
        headers=headers,
        json={"guidance": "Interpret the findings and recommend treatment."},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "banned_phrase"
    assert detail["matched_phrase"]


@pytest.mark.asyncio
async def test_patch_specialty_unknown_key_404(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    r = await app_client.patch(
        "/api/v1/me/prompts/specialties/not_a_real_specialty",
        headers=headers,
        json={"guidance": _WELL_FORMED_GUIDANCE},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_patch_specialty_guidance_non_clinician_forbidden(
    app_client: AsyncClient,
) -> None:
    """Support roles can READ specialties but not edit a physician's guidance."""
    r = await app_client.patch(
        _SPECIALTY_URL,
        headers={"Authorization": f"Bearer ADMIN:{uuid.uuid4()}"},
        json={"guidance": _WELL_FORMED_GUIDANCE},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_delete_specialty_guidance_clears_override(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = marie
    await app_client.patch(
        _SPECIALTY_URL, headers=headers, json={"guidance": _WELL_FORMED_GUIDANCE}
    )
    r = await app_client.delete(_SPECIALTY_URL, headers=headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["is_overridden"] is False
    assert payload["user_guidance"] is None
    assert payload["active_guidance"] == payload["guidance"]


@pytest.mark.asyncio
async def test_delete_specialty_guidance_idempotent(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Deleting with no saved override still returns 200 at the default."""
    _, headers = marie
    r = await app_client.delete(_SPECIALTY_URL, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_overridden"] is False


@pytest.mark.asyncio
async def test_specialty_guidance_physician_isolation(
    app_client: AsyncClient,
    marie: tuple[uuid.UUID, dict[str, str]],
    perry: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """Marie's saved guidance never appears in Perry's view."""
    _, marie_headers = marie
    _, perry_headers = perry
    await app_client.patch(
        _SPECIALTY_URL,
        headers=marie_headers,
        json={"guidance": _WELL_FORMED_GUIDANCE},
    )
    r = await app_client.get(
        "/api/v1/me/prompts/specialties", headers=perry_headers
    )
    ortho = next(s for s in r.json() if s["key"] == _SPECIALTY)
    assert ortho["is_overridden"] is False
    assert ortho["user_guidance"] is None


@pytest.mark.asyncio
async def test_specialty_override_persisted_with_namespaced_id(
    app_client: AsyncClient,
    db_session: AsyncSession,
    marie: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """The row lands in prompt_overrides under the specialty_style: namespace
    so it never collides with a registry-prompt override."""
    from app.core.models import PromptOverrideModel

    marie_id, headers = marie
    await app_client.patch(
        _SPECIALTY_URL, headers=headers, json={"guidance": _WELL_FORMED_GUIDANCE}
    )
    stmt = select(PromptOverrideModel).where(
        PromptOverrideModel.owner_id == marie_id,
        PromptOverrideModel.prompt_id == f"specialty_style:{_SPECIALTY}",
    )
    row = (await db_session.execute(stmt)).scalar_one()
    assert row.user_prompt_text == _WELL_FORMED_GUIDANCE
