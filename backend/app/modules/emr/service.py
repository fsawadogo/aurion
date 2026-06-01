"""EMR write-back orchestration service (#57).

Walks the approved note → FHIR serializer → connector → persist
attempt to `emr_write_backs`. Returns the persisted row so the route
can build an audit event without re-discovering connector / fingerprint.

State transitions:
  queued → sending → sent          (success)
  queued → sending → failed         (terminal connector error)
                  ↳ retry scheduled  (retryable connector error)

Ownership is enforced by the route; this module trusts its inputs.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import EmrWriteBackModel
from app.core.types import Note
from app.modules.emr.base import EmrConnectorError
from app.modules.emr.fhir import serialize_payload
from app.modules.emr.registry import get_connector, get_default_connector

logger = logging.getLogger("aurion.emr.service")


def _fingerprint(payload: bytes) -> str:
    """sha256 hex digest of the payload bytes — the audit-trail anchor.

    Lets us answer "was the same payload sent twice?" without storing
    the payload itself (which would create a second permanent copy of
    PHI we'd have to manage)."""
    return hashlib.sha256(payload).hexdigest()


def _sanitize_error(message: str, max_len: int = 500) -> str:
    """Defensive truncation for connector error messages.

    Connectors are required (by contract in `EmrConnector` docstring)
    to scrub PHI before raising; this is the belt-and-suspenders for
    when a misbehaving connector echoes more than it should."""
    if len(message) > max_len:
        return message[:max_len] + " …(truncated)"
    return message


# Retry schedule (exponential backoff). Index = attempt_count we're
# scheduling NEXT (so after the first failure, attempt 2 fires in
# 60s; after the second, attempt 3 in 5min; etc.). After exhausting
# the schedule, the row stays at status=failed without a
# scheduled_at — terminal.
_RETRY_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900)

# Maximum total attempts before we give up. Each subsequent attempt
# stacks on the previous one's audit row via attempt_count.
_MAX_ATTEMPTS: int = 1 + len(_RETRY_BACKOFF_SECONDS)


def _next_scheduled_at(next_attempt_number: int) -> Optional[datetime]:
    """Return the scheduled_at for the upcoming attempt, or None when
    the schedule is exhausted (terminal failure).

    next_attempt_number is 1-indexed: passing 2 picks the FIRST backoff
    slot (60s); passing 3 picks the second; etc."""
    # The first attempt fires immediately — no entry in the backoff
    # array for it.
    if next_attempt_number <= 1:
        return None
    slot = next_attempt_number - 2
    if slot < 0 or slot >= len(_RETRY_BACKOFF_SECONDS):
        return None
    return datetime.now(timezone.utc) + timedelta(
        seconds=_RETRY_BACKOFF_SECONDS[slot]
    )


async def send_to_emr(
    session_id: uuid.UUID,
    note: Note,
    *,
    author_user_id: str,
    external_reference_id: str | None,
    connector_key: Optional[str],
    db: AsyncSession,
) -> EmrWriteBackModel:
    """Build payload, persist a row, run the connector, update with
    result. Returns the EmrWriteBackModel row in its final state for
    this attempt.

    Never raises — connector errors are captured into row.status =
    failed + error_reason. The route maps row.status to the HTTP
    response.
    """
    connector = (
        get_connector(connector_key) if connector_key else get_default_connector()
    )
    payload = serialize_payload(
        str(session_id),
        note,
        author_user_id=author_user_id,
        external_reference_id=external_reference_id,
    )
    fingerprint = _fingerprint(payload)

    row = EmrWriteBackModel(
        id=uuid.uuid4(),
        session_id=session_id,
        connector=connector.key,
        status="queued",
        payload_fingerprint=fingerprint,
        attempt_count=0,
    )
    db.add(row)
    await db.flush()

    # Move to sending; bump attempt count before the call so a hung
    # connector doesn't leave the row in a confusing "queued but
    # already running" state.
    row.status = "sending"
    row.attempt_count = row.attempt_count + 1
    await db.flush()

    try:
        result = await connector.send(str(session_id), payload)
    except EmrConnectorError as exc:
        row.status = "failed"
        row.error_reason = _sanitize_error(str(exc))
        # Retryable failures get a scheduled_at for the worker to
        # pick up; terminal failures stay unscheduled. The schedule
        # exhaustion check inside _next_scheduled_at handles the
        # "too many attempts already" path — returns None, which we
        # treat as terminal even when the connector said retryable.
        if exc.retryable:
            row.scheduled_at = _next_scheduled_at(row.attempt_count + 1)
        logger.warning(
            "emr write-back: connector=%s session=%s failed "
            "(retryable=%s scheduled_at=%s): %s",
            connector.key, session_id, exc.retryable, row.scheduled_at, exc,
        )
        await db.flush()
        return row
    except Exception as exc:  # pragma: no cover — defensive
        # Connector contract says raise EmrConnectorError; if a
        # connector raises something else, treat as terminal so we
        # don't loop, but still fail the row cleanly. No scheduled_at.
        row.status = "failed"
        row.error_reason = _sanitize_error(
            f"Unexpected connector exception: {type(exc).__name__}"
        )
        logger.exception(
            "emr write-back: connector=%s session=%s raised unexpected",
            connector.key, session_id,
        )
        await db.flush()
        return row

    row.status = "sent"
    row.external_id = result.external_id
    row.sent_at = datetime.now(timezone.utc)
    # Clear any retry schedule — succeeded.
    row.scheduled_at = None
    await db.flush()
    return row


async def list_for_session(
    session_id: uuid.UUID, db: AsyncSession
) -> list[EmrWriteBackModel]:
    """All write-back attempts for a session, newest first."""
    stmt = (
        select(EmrWriteBackModel)
        .where(EmrWriteBackModel.session_id == session_id)
        .order_by(EmrWriteBackModel.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_for_session(
    write_back_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[EmrWriteBackModel]:
    """Fetch a write-back row scoped to its session."""
    stmt = select(EmrWriteBackModel).where(
        EmrWriteBackModel.id == write_back_id,
        EmrWriteBackModel.session_id == session_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_due_for_retry(
    db: AsyncSession, *, now: Optional[datetime] = None, limit: int = 50,
) -> list[EmrWriteBackModel]:
    """Find failed rows whose retry slot has come due.

    `now` is injectable for tests; production passes None (current
    UTC time). Limit caps the batch size — one retry pass handles at
    most `limit` rows; the worker can run again to drain the rest.

    Returns rows ordered by scheduled_at ascending (oldest-due first)
    so a backed-up queue gets serviced fairly.
    """
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(EmrWriteBackModel)
        .where(
            EmrWriteBackModel.status == "failed",
            EmrWriteBackModel.scheduled_at.is_not(None),
            EmrWriteBackModel.scheduled_at <= now,
            EmrWriteBackModel.attempt_count < _MAX_ATTEMPTS,
        )
        .order_by(EmrWriteBackModel.scheduled_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def retry_row(
    row: EmrWriteBackModel,
    note: Note,
    *,
    author_user_id: str,
    external_reference_id: str | None,
    db: AsyncSession,
) -> EmrWriteBackModel:
    """Re-run the connector against the same write-back row.

    The row's attempt_count bumps; scheduled_at clears on success or
    gets pushed to the next backoff slot on retryable failure; goes
    to None when the schedule is exhausted (terminal).

    The payload is re-serialized from the note — we DELIBERATELY
    don't store payloads (PHI; EMR is source of truth post-send),
    so a retry produces a payload with the same content as the
    original attempt. The fingerprint comparison is a sanity check;
    a mismatch means the note changed between attempts (physician
    edited; this is allowed but worth logging).
    """
    connector = get_connector(row.connector)
    payload = serialize_payload(
        str(row.session_id),
        note,
        author_user_id=author_user_id,
        external_reference_id=external_reference_id,
    )
    new_fingerprint = _fingerprint(payload)
    if new_fingerprint != row.payload_fingerprint:
        # Note changed between the original attempt and the retry —
        # log + update the fingerprint so the audit story reflects
        # what was actually sent on this attempt.
        logger.info(
            "emr retry: payload fingerprint changed for row=%s "
            "(original=%s new=%s) — note was edited",
            row.id, row.payload_fingerprint[:12], new_fingerprint[:12],
        )
        row.payload_fingerprint = new_fingerprint

    row.status = "sending"
    row.attempt_count = row.attempt_count + 1
    # Clear scheduled_at while running so a concurrent worker doesn't
    # also pick this row up.
    row.scheduled_at = None
    await db.flush()

    try:
        result = await connector.send(str(row.session_id), payload)
    except EmrConnectorError as exc:
        row.status = "failed"
        row.error_reason = _sanitize_error(str(exc))
        if exc.retryable:
            row.scheduled_at = _next_scheduled_at(row.attempt_count + 1)
        logger.warning(
            "emr retry: connector=%s session=%s attempt=%d failed "
            "(retryable=%s scheduled_at=%s): %s",
            connector.key, row.session_id, row.attempt_count,
            exc.retryable, row.scheduled_at, exc,
        )
        await db.flush()
        return row
    except Exception as exc:
        row.status = "failed"
        row.error_reason = _sanitize_error(
            f"Unexpected connector exception: {type(exc).__name__}"
        )
        logger.exception(
            "emr retry: connector=%s session=%s raised unexpected",
            connector.key, row.session_id,
        )
        await db.flush()
        return row

    row.status = "sent"
    row.external_id = result.external_id
    row.sent_at = datetime.now(timezone.utc)
    row.scheduled_at = None
    row.error_reason = None
    await db.flush()
    return row
