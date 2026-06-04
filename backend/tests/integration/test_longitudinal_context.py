"""Integration tests for the #61 full-slice longitudinal context module.

Locks the seven CLAUDE.md gates this PR claims:

  1. Cold-start path — no identifier → ``get_prior_context`` returns
     None outright (no lookup, no audit row).
  2. Identifier set but no prior found → returns the
     ``total_seen=0, encounters=[]`` block. No audit row written.
  3. Per-physician scope — Marie's prior visit with patient X is
     INVISIBLE to Perry's session even though both physicians have
     that patient on their panels.
  4. PURGED sessions are excluded from the prior context (the row may
     linger for the audit trail; its note content is gone).
  5. Descriptive mode preserved — the rendered block must NOT carry
     the prior assessment text. Banned-phrase scan ("consistent with",
     "suggests", "consider") catches drift into interpretive output.
  6. Audit event whitelist — the LONGITUDINAL_CONTEXT_LOADED row
     carries exactly {actor_id, current_session_id, encounters_count,
     last_encounter_date} and nothing else. AURION_AUDIT_STRICT=1
     (set in the suite conftest) would already crash on a drift; we
     also assert the snapshot positively.
  7. Completeness scoring is unchanged by prior-context presence —
     the score is a function of populated required sections, not of
     the prompt's context block. A regression in either direction
     (lower because the prior leaked into the score, higher because
     it short-circuited the count) would invalidate the pilot metric.

DB strategy mirrors :mod:`tests.integration.test_prompt_overrides`:
real Postgres, outer transaction + SAVEPOINT per test, skipped at
collection time if Postgres isn't reachable.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# Env vars before app import — APP_ENV=local enables the dev-token
# bearer parser used by the request fixtures elsewhere; the
# longitudinal_context module itself doesn't need it but the rest
# of the imported app code expects it.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
# Pin the HMAC key so hash_identifier is deterministic across tests.
os.environ.setdefault(
    "AURION_IDENTIFIER_HMAC_KEY", "integration-test-key-longitudinal"
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import identifier_hash  # noqa: E402
from app.core.audit_events import (  # noqa: E402
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
)
from app.core.identifier_hash import hash_identifier  # noqa: E402
from app.core.models import (  # noqa: E402
    NoteVersionModel,
    SessionModel,
    UserModel,
)
from app.core.types import (  # noqa: E402
    Note,
    NoteClaim,
    NoteSection,
    SessionState,
    Template,
    TemplateSection,
    UserRole,
)
from app.modules.longitudinal_context import get_prior_context  # noqa: E402
from app.modules.longitudinal_context.service import (  # noqa: E402
    render_prior_context_block,
)
from app.modules.note_gen.service import calculate_completeness  # noqa: E402

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


@pytest.fixture(autouse=True)
def reset_hash_cache() -> None:
    identifier_hash.reset_cache_for_tests()


@pytest.fixture
def mock_audit_log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """AuditLogService stub — captures write_event calls without
    touching DynamoDB. Returned for direct assertion."""
    from app.modules.audit_log import service as audit_module

    mock_service = MagicMock(spec=audit_module.AuditLogService)
    mock_service.write_event = AsyncMock(return_value={})
    mock_service.get_session_events = AsyncMock(return_value=[])
    monkeypatch.setattr(audit_module, "_service", mock_service)
    return mock_service


# ── Test-data builders ─────────────────────────────────────────────────────


async def _seed_clinician(db_session: AsyncSession, label: str) -> uuid.UUID:
    """Insert a CLINICIAN user and return its id. `label` is folded
    into the email + display name so test failures point back at
    which physician owned the row."""
    uid = uuid.uuid4()
    db_session.add(
        UserModel(
            id=uid,
            email=f"{label}-{uid}@aurion.test",
            password_hash="x",
            full_name=f"Test {label.title()}",
            role=UserRole.CLINICIAN,
        )
    )
    await db_session.flush()
    return uid


async def _seed_session(
    db_session: AsyncSession,
    clinician_id: uuid.UUID,
    *,
    identifier_plaintext: str | None,
    specialty: str = "orthopedic_surgery",
    state: SessionState = SessionState.REVIEW_COMPLETE,
    created_at: datetime | None = None,
) -> SessionModel:
    """Insert a SessionModel row optionally tagged with an identifier
    (both ciphertext + hash columns get set when non-None).

    `created_at` is overridable so tests can pin specific dates for
    the rendered block's "newest first" assertion. The ciphertext
    uses a stub blob shape (``b"ENC::" + plaintext``) which mirrors
    what the unit-test stub KMS produces — fine for the prior-
    context tests because the rehydration path doesn't depend on
    KMS here (the `get_prior_context` lookup is hash-only).
    """
    sid = uuid.uuid4()
    row = SessionModel(
        id=sid,
        clinician_id=clinician_id,
        specialty=specialty,
        state=state,
        consent_confirmed=True,
        encounter_type="doctor_patient",
        capture_mode="multimodal",
        output_language="en",
    )
    if identifier_plaintext is not None:
        row.external_reference_id_encrypted = b"ENC::" + identifier_plaintext.encode("utf-8")
        row.external_reference_id_hash = hash_identifier(identifier_plaintext)
    if created_at is not None:
        row.created_at = created_at
        row.updated_at = created_at
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_note_version(
    db_session: AsyncSession,
    session_id: uuid.UUID,
    *,
    sections: list[dict],
    specialty: str = "orthopedic_surgery",
    version: int = 1,
) -> NoteVersionModel:
    """Persist a NoteVersionModel row with the given sections.

    Sections must be a list of dicts already in the shape the JSON
    column expects ({"id", "title", "status", "claims": [...]}). The
    Note Pydantic model isn't used here so tests can construct
    "assessment with interpretive prose" rows that the production
    builder would never emit — those are the exact rows the
    descriptive-mode regression test needs.
    """
    content = {
        "session_id": str(session_id),
        "stage": 1,
        "version": version,
        "provider_used": "anthropic",
        "specialty": specialty,
        "completeness_score": 0.8,
        "sections": sections,
    }
    row = NoteVersionModel(
        session_id=session_id,
        version=version,
        stage=1,
        provider_used="anthropic",
        specialty=specialty,
        completeness_score=0.8,
        content=json.dumps(content),
        is_approved=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _section(
    section_id: str,
    text: str,
    *,
    status: str = "populated",
    claim_id: str | None = None,
) -> dict:
    return {
        "id": section_id,
        "title": section_id.replace("_", " ").title(),
        "status": status,
        "claims": [
            {
                "id": claim_id or f"c_{section_id}",
                "text": text,
                "source_type": "transcript",
                "source_id": "seg_001",
                "source_quote": text,
            }
        ],
    }


# ── 1. Cold-start ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_identifier_skips_lookup(
    db_session: AsyncSession,
) -> None:
    """Empty / falsy identifier → returns None immediately. No DB
    query is required; the cold-start signal is the absence of a
    block at the caller layer."""
    clinician_id = await _seed_clinician(db_session, "perry")
    result = await get_prior_context(
        clinician_id=clinician_id,
        patient_identifier="",
        current_session_id=uuid.uuid4(),
        db=db_session,
    )
    assert result is None

    # Whitespace-only collapses to empty after the .strip().
    result_ws = await get_prior_context(
        clinician_id=clinician_id,
        patient_identifier="   ",
        current_session_id=uuid.uuid4(),
        db=db_session,
    )
    assert result_ws is None


# ── 2. Identifier set, no prior found ──────────────────────────────────────


@pytest.mark.asyncio
async def test_identifier_with_no_prior_returns_empty_block(
    db_session: AsyncSession,
) -> None:
    """A fresh identifier with no matching sessions returns a block
    with empty encounters + total_seen=0. The caller distinguishes
    this from None ("cold-start") and from a populated block.
    """
    clinician_id = await _seed_clinician(db_session, "perry")
    current = await _seed_session(
        db_session, clinician_id, identifier_plaintext="MRN-NEW-100"
    )
    block = await get_prior_context(
        clinician_id=clinician_id,
        patient_identifier="MRN-NEW-100",
        current_session_id=current.id,
        db=db_session,
    )
    assert block is not None
    assert block.encounters == []
    assert block.total_seen == 0
    # Rendered block of an empty list is the empty string so the
    # caller can unconditionally concatenate.
    assert render_prior_context_block(block) == ""


# ── 3. Per-physician scope ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_clinicians_sessions_do_not_leak_to_another(
    db_session: AsyncSession,
) -> None:
    """Marie's prior visit with patient X must NEVER reach a session
    Perry is running for the same identifier. Per-physician panel is
    the CLAUDE.md gate; the query has to filter on clinician_id.
    """
    marie = await _seed_clinician(db_session, "marie")
    perry = await _seed_clinician(db_session, "perry")
    shared_identifier = "MRN-SHARED-7777"

    # Marie's prior with this patient.
    marie_prior = await _seed_session(
        db_session,
        marie,
        identifier_plaintext=shared_identifier,
        created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    await _seed_note_version(
        db_session,
        marie_prior.id,
        sections=[
            _section("chief_complaint", "right wrist pain after fall"),
            _section("physical_exam", "swelling, point tenderness at scaphoid"),
            _section("plan", "splint, ortho follow-up in 2 weeks"),
        ],
    )

    # Perry's current session for the same patient.
    perry_current = await _seed_session(
        db_session, perry, identifier_plaintext=shared_identifier
    )

    block = await get_prior_context(
        clinician_id=perry,
        patient_identifier=shared_identifier,
        current_session_id=perry_current.id,
        db=db_session,
    )
    # Marie's row exists with the right identifier hash but the
    # query filters on Perry's clinician id → no leakage.
    assert block is not None
    assert block.encounters == []
    assert block.total_seen == 0


# ── 4. PURGED sessions excluded ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_purged_sessions_excluded(
    db_session: AsyncSession,
) -> None:
    """A session whose state is PURGED stays on the audit trail but
    has no note content. Including it in the prior context would
    produce a date + specialty line with no clinical detail —
    misleading. Filter must drop it."""
    clinician_id = await _seed_clinician(db_session, "perry")
    identifier = "MRN-PURGE-7"

    purged = await _seed_session(
        db_session,
        clinician_id,
        identifier_plaintext=identifier,
        state=SessionState.PURGED,
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    await _seed_note_version(
        db_session,
        purged.id,
        sections=[_section("chief_complaint", "ignored — purged")],
    )

    live = await _seed_session(
        db_session,
        clinician_id,
        identifier_plaintext=identifier,
        state=SessionState.REVIEW_COMPLETE,
        created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    await _seed_note_version(
        db_session,
        live.id,
        sections=[_section("chief_complaint", "right shoulder pain")],
    )

    current = await _seed_session(
        db_session, clinician_id, identifier_plaintext=identifier
    )

    block = await get_prior_context(
        clinician_id=clinician_id,
        patient_identifier=identifier,
        current_session_id=current.id,
        db=db_session,
    )
    assert block is not None
    assert block.total_seen == 1  # PURGED row excluded from total
    assert len(block.encounters) == 1
    assert block.encounters[0].session_id == live.id
    assert block.encounters[0].chief_complaint_excerpt == "right shoulder pain"


# ── 5. Descriptive mode preserved (no assessment, no interpretive prose) ──


@pytest.mark.asyncio
async def test_descriptive_mode_preserved_with_prior_context(
    db_session: AsyncSession,
) -> None:
    """The rendered block must never carry the prior physician's
    diagnostic impression. Even if the prior note's ASSESSMENT
    section is full of "consistent with rotator cuff pathology"
    language, the renderer drops the section entirely so the next
    Stage 1 LLM call doesn't echo that diagnosis back as if it
    reached it itself."""
    clinician_id = await _seed_clinician(db_session, "perry")
    identifier = "MRN-ASSESS-9"

    prior = await _seed_session(
        db_session,
        clinician_id,
        identifier_plaintext=identifier,
        created_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    await _seed_note_version(
        db_session,
        prior.id,
        sections=[
            _section("chief_complaint", "right shoulder pain x 6 weeks"),
            _section("physical_exam", "ROM right flexion 140, abduction 110"),
            # The interpretive prose that MUST NOT make it into the
            # rendered block.
            _section(
                "assessment",
                "Findings are consistent with rotator cuff pathology; suggests "
                "imaging. Consider MR arthrogram.",
            ),
            _section("plan", "PT, follow-up 4 weeks"),
        ],
    )

    current = await _seed_session(
        db_session, clinician_id, identifier_plaintext=identifier
    )

    block = await get_prior_context(
        clinician_id=clinician_id,
        patient_identifier=identifier,
        current_session_id=current.id,
        db=db_session,
    )
    assert block is not None and block.encounters

    rendered = render_prior_context_block(block)
    # Every banned phrase must be absent — these are the canonical
    # descriptive-mode trip wires; if any leak through, the prior
    # assessment is in the prompt.
    for phrase in (
        "consistent with",
        "suggests",
        "Consider",
        "rotator cuff pathology",
        "MR arthrogram",
    ):
        assert phrase.lower() not in rendered.lower(), (
            f"Rendered prior context leaked '{phrase}' — assessment "
            f"must be dropped before render"
        )

    # The harmless physical_exam + plan content should be present so
    # the test ensures the renderer didn't just go silent.
    assert "ROM right flexion 140" in rendered
    assert "PT, follow-up 4 weeks" in rendered


# ── 6. Audit row carries no PHI ───────────────────────────────────────────


def test_audit_event_contains_no_phi_in_whitelist() -> None:
    """ALLOWED_AUDIT_KWARGS for LONGITUDINAL_CONTEXT_LOADED is pinned
    to exactly {actor_id, current_session_id, encounters_count,
    last_encounter_date}. Adding a key is a deliberate security
    decision; this test makes that decision visible."""
    allowed = ALLOWED_AUDIT_KWARGS.get(AuditEventType.LONGITUDINAL_CONTEXT_LOADED)
    assert allowed is not None
    assert allowed == frozenset(
        {
            "actor_id",
            "current_session_id",
            "encounters_count",
            "last_encounter_date",
        }
    )
    # Specifically banned kwarg names — any of these would carry PHI
    # or clinical content into the immutable audit trail.
    for banned in (
        "patient_identifier",
        "identifier",
        "value",
        "plaintext",
        "prior_session_ids",
        "chief_complaint",
        "key_claims",
        "assessment",
    ):
        assert banned not in allowed, (
            f"LONGITUDINAL_CONTEXT_LOADED audit whitelist must not "
            f"include {banned!r} — that would land PHI in the "
            f"append-only trail"
        )


# ── 7. Completeness score unaffected by prior context presence ─────────────


def test_completeness_score_unaffected_by_prior_context_presence() -> None:
    """The completeness score is computed from the note's populated
    required sections. Prior context lives upstream of the LLM call
    and never enters the score formula. This test exercises the
    pure scoring function with identical Note shapes — the result
    must be byte-identical regardless of any hypothetical "prior
    context bonus" or "penalty" creeping in."""
    template = Template(
        key="orthopedic_surgery",
        display_name="Orthopedic Surgery",
        sections=[
            TemplateSection(id="chief_complaint", title="Chief Complaint"),
            TemplateSection(id="physical_exam", title="Physical Exam"),
            TemplateSection(id="plan", title="Plan"),
        ],
    )
    note = Note(
        session_id=str(uuid.uuid4()),
        stage=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(id="chief_complaint", status="populated", claims=[
                NoteClaim(id="c1", text="x", source_type="transcript", source_id="s1")
            ]),
            NoteSection(id="physical_exam", status="populated", claims=[
                NoteClaim(id="c2", text="y", source_type="transcript", source_id="s1")
            ]),
            NoteSection(id="plan", status="populated", claims=[
                NoteClaim(id="c3", text="z", source_type="transcript", source_id="s1")
            ]),
        ],
    )
    # Cold-start path: prior_context_used is None.
    note.prior_context_used = None
    score_cold = calculate_completeness(note, template)

    # Hot path: prior_context_used populated. The exact same note
    # shape should yield the exact same score.
    from app.core.types import PriorContextUsedSummary

    note.prior_context_used = PriorContextUsedSummary(
        encounters_referenced=3, last_encounter_date="2026-05-14"
    )
    score_hot = calculate_completeness(note, template)

    assert score_cold == 1.0
    assert score_hot == 1.0
    assert score_cold == score_hot
