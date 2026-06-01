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
from datetime import datetime, timezone
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
        logger.warning(
            "emr write-back: connector=%s session=%s failed (retryable=%s): %s",
            connector.key, session_id, exc.retryable, exc,
        )
        await db.flush()
        return row
    except Exception as exc:  # pragma: no cover — defensive
        # Connector contract says raise EmrConnectorError; if a
        # connector raises something else, treat as terminal so we
        # don't loop, but still fail the row cleanly.
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
