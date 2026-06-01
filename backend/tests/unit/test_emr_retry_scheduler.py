"""Unit tests for the EMR retry scheduler (#57 follow-up).

Covers:
  * _next_scheduled_at: returns None for first attempt; returns 60s
    for the first retry; exhausts after the configured backoff
    schedule
  * send_to_emr now sets scheduled_at on retryable failures + clears
    it on success
  * send_to_emr does NOT set scheduled_at on terminal failures
  * send_to_emr exhausts schedule after _MAX_ATTEMPTS
  * retry_row bumps attempt_count, clears scheduled_at on success,
    reschedules on retryable failure, terminates on schedule
    exhaustion
  * retry_row detects payload-fingerprint change between attempts
    (note was edited) and updates the row
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.emr import service as emr_service
from app.modules.emr.base import (
    EmrConnector,
    EmrConnectorError,
    EmrSendResult,
)
from app.modules.emr.registry import register_connector

# ── _next_scheduled_at ──────────────────────────────────────────────────


def test_next_scheduled_at_first_attempt_none():
    """The first attempt fires immediately — no backoff slot."""
    assert emr_service._next_scheduled_at(1) is None


def test_next_scheduled_at_first_retry_is_60s():
    """After the first failure, schedule attempt 2 → 60s out."""
    before = datetime.now(timezone.utc)
    when = emr_service._next_scheduled_at(2)
    after = datetime.now(timezone.utc)
    assert when is not None
    # Approximate — clock can move during the call. Sanity range:
    # ~60s out, with a 5s slop window.
    delta = when - before
    assert timedelta(seconds=55) <= delta <= timedelta(seconds=65)
    assert when <= after + timedelta(seconds=65)


def test_next_scheduled_at_second_retry_is_5min():
    when = emr_service._next_scheduled_at(3)
    assert when is not None
    delta = when - datetime.now(timezone.utc)
    assert timedelta(seconds=290) <= delta <= timedelta(seconds=310)


def test_next_scheduled_at_third_retry_is_15min():
    when = emr_service._next_scheduled_at(4)
    assert when is not None
    delta = when - datetime.now(timezone.utc)
    assert timedelta(seconds=890) <= delta <= timedelta(seconds=910)


def test_next_scheduled_at_exhausted_returns_none():
    """After 4 attempts (1 original + 3 retries), schedule is done.
    `_next_scheduled_at(5)` is the "scheduling the 5th attempt" call;
    we don't budget for that — return None so the row stays terminal."""
    assert emr_service._next_scheduled_at(5) is None


def test_next_scheduled_at_far_future_returns_none():
    """Defensive — wildly out-of-range inputs don't index past the array."""
    assert emr_service._next_scheduled_at(100) is None
    assert emr_service._next_scheduled_at(0) is None
    assert emr_service._next_scheduled_at(-1) is None


# ── send_to_emr — retry scheduling integration ──────────────────────────


class _MockSession:
    """Lightweight AsyncSession stand-in — same shape as the one used
    in test_emr_service.py."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


class _SuccessConnector(EmrConnector):
    key = "_test_retry_success"

    async def send(self, session_id, payload):
        return EmrSendResult(external_id=f"ok-{session_id}")


class _RetryableFailConnector(EmrConnector):
    key = "_test_retry_fail"

    async def send(self, session_id, payload):
        raise EmrConnectorError("temporary blip", retryable=True)


class _TerminalFailConnector(EmrConnector):
    key = "_test_term_fail"

    async def send(self, session_id, payload):
        raise EmrConnectorError("bad auth", retryable=False)


def _note_fixture():
    from app.core.types import Note, NoteClaim, NoteSection

    return Note(
        session_id="33333333-3333-3333-3333-333333333333",
        stage=2,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.8,
        sections=[
            NoteSection(
                id="hpi",
                title="HPI",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c001",
                        text="Pain three weeks.",
                        source_type="transcript",
                        source_id="seg_1",
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_send_to_emr_success_clears_scheduled_at():
    """Happy path leaves no retry breadcrumb. We bake this in
    explicitly because the orchestration now also sets scheduled_at
    on retryable failures — a successful send must clear it."""
    register_connector(_SuccessConnector())
    db = _MockSession()
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        connector_key="_test_retry_success",
        db=db,  # type: ignore[arg-type]
    )
    assert row.status == "sent"
    assert row.scheduled_at is None


@pytest.mark.asyncio
async def test_send_to_emr_retryable_failure_sets_scheduled_at():
    register_connector(_RetryableFailConnector())
    db = _MockSession()
    before = datetime.now(timezone.utc)
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        connector_key="_test_retry_fail",
        db=db,  # type: ignore[arg-type]
    )
    assert row.status == "failed"
    assert row.scheduled_at is not None
    # First retry slot is 60s.
    delta = row.scheduled_at - before
    assert timedelta(seconds=55) <= delta <= timedelta(seconds=70)
    assert row.attempt_count == 1


@pytest.mark.asyncio
async def test_send_to_emr_terminal_failure_no_scheduled_at():
    """Auth failure → no retry will help; scheduled_at stays None."""
    register_connector(_TerminalFailConnector())
    db = _MockSession()
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        connector_key="_test_term_fail",
        db=db,  # type: ignore[arg-type]
    )
    assert row.status == "failed"
    assert row.scheduled_at is None


# ── retry_row — re-running the connector ────────────────────────────────


@pytest.mark.asyncio
async def test_retry_row_success_clears_scheduled_at():
    """A succeeding retry: status=sent + scheduled_at=None +
    error_reason cleared + attempt_count bumped."""
    from app.core.models import EmrWriteBackModel

    register_connector(_SuccessConnector())
    db = _MockSession()
    row = EmrWriteBackModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        connector="_test_retry_success",
        status="failed",
        payload_fingerprint="x" * 64,
        attempt_count=1,
        error_reason="prior failure",
        scheduled_at=datetime.now(timezone.utc),
    )
    updated = await emr_service.retry_row(
        row,
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        db=db,  # type: ignore[arg-type]
    )
    assert updated.status == "sent"
    assert updated.scheduled_at is None
    assert updated.error_reason is None
    assert updated.attempt_count == 2
    assert updated.external_id is not None


@pytest.mark.asyncio
async def test_retry_row_retryable_failure_reschedules():
    """A retry that fails again gets pushed to the next backoff slot
    if the schedule still has budget."""
    from app.core.models import EmrWriteBackModel

    register_connector(_RetryableFailConnector())
    db = _MockSession()
    row = EmrWriteBackModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        connector="_test_retry_fail",
        status="failed",
        payload_fingerprint="x" * 64,
        attempt_count=1,
        error_reason="prior",
        scheduled_at=datetime.now(timezone.utc),
    )
    updated = await emr_service.retry_row(
        row,
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        db=db,  # type: ignore[arg-type]
    )
    assert updated.status == "failed"
    assert updated.scheduled_at is not None  # next slot reserved
    assert updated.attempt_count == 2


@pytest.mark.asyncio
async def test_retry_row_exhaustion_terminates():
    """Once we've used all budget retry slots, retry-with-retryable-
    failure goes terminal (scheduled_at stays None even though the
    connector said retryable)."""
    from app.core.models import EmrWriteBackModel

    register_connector(_RetryableFailConnector())
    db = _MockSession()
    # attempt_count=3 means this is the 4th attempt → outside the
    # 3-slot backoff array → no further schedule.
    row = EmrWriteBackModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        connector="_test_retry_fail",
        status="failed",
        payload_fingerprint="x" * 64,
        attempt_count=3,
        scheduled_at=datetime.now(timezone.utc),
    )
    updated = await emr_service.retry_row(
        row,
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        db=db,  # type: ignore[arg-type]
    )
    assert updated.status == "failed"
    assert updated.scheduled_at is None  # terminal — no more retries
    assert updated.attempt_count == 4


@pytest.mark.asyncio
async def test_retry_row_terminal_failure_no_reschedule():
    """If the connector now returns a terminal error (e.g. auth
    revoked between attempts), scheduled_at stays None."""
    from app.core.models import EmrWriteBackModel

    register_connector(_TerminalFailConnector())
    db = _MockSession()
    row = EmrWriteBackModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        connector="_test_term_fail",
        status="failed",
        payload_fingerprint="x" * 64,
        attempt_count=1,
        scheduled_at=datetime.now(timezone.utc),
    )
    updated = await emr_service.retry_row(
        row,
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        db=db,  # type: ignore[arg-type]
    )
    assert updated.status == "failed"
    assert updated.scheduled_at is None


@pytest.mark.asyncio
async def test_retry_row_detects_fingerprint_change():
    """If the note was edited between attempts, the new payload's
    fingerprint differs from the row's. The retry updates the
    fingerprint so the row reflects what was sent on THIS attempt."""
    from app.core.models import EmrWriteBackModel

    register_connector(_SuccessConnector())
    db = _MockSession()
    row = EmrWriteBackModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        connector="_test_retry_success",
        status="failed",
        # Intentionally wrong fingerprint — simulates "note edited
        # since original attempt".
        payload_fingerprint="0" * 64,
        attempt_count=1,
        scheduled_at=datetime.now(timezone.utc),
    )
    updated = await emr_service.retry_row(
        row,
        _note_fixture(),
        author_user_id="u",
        external_reference_id=None,
        db=db,  # type: ignore[arg-type]
    )
    assert updated.status == "sent"
    # Fingerprint should have been replaced — no longer the bogus 0...0
    assert updated.payload_fingerprint != "0" * 64
    assert len(updated.payload_fingerprint) == 64  # still sha256


# ── _MAX_ATTEMPTS sanity ─────────────────────────────────────────────────


def test_max_attempts_matches_schedule():
    """_MAX_ATTEMPTS = 1 + len(_RETRY_BACKOFF_SECONDS). If the backoff
    schedule grows, _MAX_ATTEMPTS must grow with it or retry_row will
    refuse to use the new slot."""
    assert emr_service._MAX_ATTEMPTS == 1 + len(emr_service._RETRY_BACKOFF_SECONDS)
