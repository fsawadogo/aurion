"""Unit tests for the clinician schedule service (#603).

Locks the PHI identifier gate, the status set + transition rules, the
note bounds, and the audit-event whitelist. DB-touching paths run
against a stubbed AsyncSession with the KMS/HMAC helpers monkeypatched to
deterministic fakes — the real owner-scoping + encrypt roundtrip through
the live route is proven in tests/integration/test_me_schedule.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType
from app.core.models import ScheduleEntryModel
from app.modules.schedule import service as sched


# ── Patient identifier gate (PHI foot-guns) ───────────────────────────────


@pytest.mark.parametrize(
    "identifier",
    ["MRN-123", "A1B2C3", "ENC-2026-0044", "12345678", "chart_9"],
)
def test_identifier_accepts_clinic_ids(identifier: str) -> None:
    """Ordinary MRN / encounter-id shapes validate."""
    assert sched.validate_patient_identifier(identifier) == identifier


@pytest.mark.parametrize(
    "identifier",
    [
        "John Smith",              # full-name shape
        "jane.doe@example.com",    # email
        "123-45-6789",             # dashed SSN
        "123456789",               # raw 9-digit SSN
        "x" * 65,                  # over the 64-char cap
    ],
)
def test_identifier_rejects_phi_foot_guns(identifier: str) -> None:
    """The obvious PHI foot-guns raise ScheduleIdentifierError (→ 422)."""
    with pytest.raises(sched.ScheduleIdentifierError):
        sched.validate_patient_identifier(identifier)


def test_identifier_error_never_echoes_value() -> None:
    """The rejection message must not contain the rejected value — it may
    itself be a patient name."""
    secret = "Jane Q Patient"
    try:
        sched.validate_patient_identifier(secret)
    except sched.ScheduleIdentifierError as exc:
        assert secret not in str(exc)
    else:  # pragma: no cover - the value above is designed to fail
        pytest.fail("expected ScheduleIdentifierError")


# ── Status validation + transitions ───────────────────────────────────────


@pytest.mark.parametrize(
    "status", ["scheduled", "in_progress", "completed", "cancelled"]
)
def test_status_valid(status: str) -> None:
    assert sched._validate_status(status) == status


def test_status_normalises_case_and_space() -> None:
    assert sched._validate_status("  In_Progress  ") == "in_progress"


def test_status_unknown_rejected() -> None:
    with pytest.raises(sched.ScheduleError, match="status must be one of"):
        sched._validate_status("done")


@pytest.mark.asyncio
async def test_status_transition_rejects_illegal() -> None:
    """A terminal status (`completed`) has no outgoing edge — re-opening
    it raises ScheduleError so the route returns 409."""
    row = ScheduleEntryModel(status="completed")
    with pytest.raises(sched.ScheduleError, match="cannot change status"):
        await sched.update_owned(row, AsyncMock(), status="scheduled")


@pytest.mark.asyncio
async def test_status_transition_allows_legal() -> None:
    row = ScheduleEntryModel(status="scheduled")
    db = AsyncMock()
    await sched.update_owned(row, db, status="in_progress")
    assert row.status == "in_progress"
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_status_same_value_is_noop_not_error() -> None:
    """Setting a terminal status to its current value must not raise —
    only a *change* to an illegal target is blocked."""
    row = ScheduleEntryModel(status="completed")
    await sched.update_owned(row, AsyncMock(), status="completed")
    assert row.status == "completed"


# ── Note bounds ───────────────────────────────────────────────────────────


def test_note_blank_becomes_none() -> None:
    assert sched._validate_note("   ") is None


def test_note_over_limit_refused() -> None:
    with pytest.raises(sched.ScheduleError, match="500"):
        sched._validate_note("x" * 501)


def test_note_strips_outer_whitespace() -> None:
    assert sched._validate_note("  pre-op consult  ") == "pre-op consult"


# ── create_for_owner — validates before any DB write, encrypts at rest ────


@pytest.mark.asyncio
async def test_add_rejects_full_name_identifier_before_db_write() -> None:
    """A full-name identifier is refused before the row is ever added."""
    db = AsyncMock()
    with pytest.raises(sched.ScheduleIdentifierError):
        await sched.create_for_owner(uuid.uuid4(), "John Smith", db)
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_add_encrypts_identifier_and_roundtrips(monkeypatch) -> None:
    """The stored identifier is ciphertext (never the plaintext bytes),
    a hash is stored for lookup, and decrypt_identifier reverses it."""
    monkeypatch.setattr(
        sched, "encrypt_str", lambda s: b"ENC::" + s.encode("utf-8")
    )
    monkeypatch.setattr(
        sched, "decrypt_str", lambda b: b.removeprefix(b"ENC::").decode("utf-8")
    )
    monkeypatch.setattr(sched, "hash_identifier", lambda s: b"HASH::" + s.encode())

    db = AsyncMock()
    db.add = MagicMock()  # .add is synchronous on a real Session
    row = await sched.create_for_owner(uuid.uuid4(), "MRN-123", db)

    assert row.patient_identifier_encrypted != b"MRN-123"
    assert row.patient_identifier_encrypted == b"ENC::MRN-123"
    assert row.patient_identifier_hash == b"HASH::MRN-123"
    assert row.status == "scheduled"
    db.add.assert_called_once()
    db.flush.assert_awaited()
    assert sched.decrypt_identifier(row) == "MRN-123"


# ── get_owned / list_for_owner — owner scope + absent → None ──────────────


@pytest.mark.asyncio
async def test_get_owned_returns_none_when_absent() -> None:
    """A missing / non-owned row yields None so the route returns 404
    (non-existence-leaking) rather than 403."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    got = await sched.get_owned(uuid.uuid4(), uuid.uuid4(), db)
    assert got is None


@pytest.mark.asyncio
async def test_list_filters_by_status_validates_filter() -> None:
    """An unknown status filter is rejected before the query runs."""
    db = AsyncMock()
    with pytest.raises(sched.ScheduleError):
        await sched.list_for_owner(uuid.uuid4(), db, status_filter="bogus")
    db.execute.assert_not_called()


# ── Audit whitelist — PHI-free ────────────────────────────────────────────


def test_schedule_audit_kwargs_are_phi_free() -> None:
    """The three schedule events must exist in the whitelist and carry
    ONLY provenance kwargs — never the patient identifier or the note."""
    expected = {
        AuditEventType.SCHEDULE_ENTRY_ADDED: {"actor_id", "entry_id"},
        AuditEventType.SCHEDULE_ENTRY_STATUS_CHANGED: {
            "actor_id",
            "entry_id",
            "status",
        },
        AuditEventType.SCHEDULE_ENTRY_REMOVED: {"actor_id", "entry_id"},
    }
    for event, allowed_expected in expected.items():
        allowed = ALLOWED_AUDIT_KWARGS.get(event)
        assert allowed is not None, f"No whitelist entry for {event}"
        assert set(allowed) == allowed_expected
        for banned in ("patient_identifier", "note", "identifier"):
            assert banned not in allowed
