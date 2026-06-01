"""Admin EMR retry-queue endpoints (#57 follow-up — retry scheduler).

The retry path is deliberately gated to ADMIN. The orchestration
flow is:

  * physician POSTs /me/notes/{id}/emr/send through their normal UI
  * retryable connector failure → row.status = failed +
    scheduled_at populated by the orchestration service
  * an admin / operator drains the retry queue via this endpoint
    (background worker auto-drain lands in a separate slice)

Why admin-only:
  * retries are infrastructure operations; they're not the same as a
    physician asking "send this again from scratch"
  * the worker that auto-drains will run as a service account, not
    as a clinician
  * exposing manual retry to a clinician would invite confusion
    between "send again" (creates a new row) and "retry the failing
    one" (mutates an existing row)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.kms_encryption import decrypt_str
from app.core.models import SessionModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.emr import service as emr_service
from app.modules.note_gen.service import get_latest_note

logger = logging.getLogger("aurion.api.admin.emr")

router = APIRouter(prefix="/admin", tags=["admin"])


class EmrRetryRowResult(BaseModel):
    """Outcome of a single retry attempt."""

    write_back_id: str
    session_id: str
    connector: str
    status: str
    attempt_count: int
    succeeded: bool
    """`True` when this retry transitioned the row to `sent`; `False`
    otherwise (still `failed`, or skipped because the session/note
    couldn't be located)."""


class EmrRetryDrainResponse(BaseModel):
    """Drain-pass summary."""

    candidates: int
    """Rows the scheduler found due. Capped at the request's `limit`."""
    attempted: int
    """Of the candidates, how many we actually re-ran. Diverges from
    `candidates` when a row's session or note can't be located
    (skipped, not retried)."""
    sent: int
    """How many flipped to status=sent."""
    still_failed: int
    """How many remain failed (may or may not have scheduled_at set
    depending on whether more retries are budgeted)."""
    results: list[EmrRetryRowResult]


class EmrRetryRequest(BaseModel):
    """Request body — limit defaults to 10. The worker calling on a
    schedule should set its own limit based on how many rows it can
    process per tick."""

    limit: int = 10


@router.get(
    "/emr/retry-queue",
    response_model=list[EmrRetryRowResult],
)
async def list_emr_retry_queue(
    limit: int = Query(50, ge=1, le=500),
    _user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[EmrRetryRowResult]:
    """Read-only view of the rows currently due for retry.

    Useful for the admin UI to surface "N retries pending" without
    triggering a drain pass."""
    due = await emr_service.list_due_for_retry(db, limit=limit)
    return [
        EmrRetryRowResult(
            write_back_id=str(row.id),
            session_id=str(row.session_id),
            connector=row.connector,
            status=row.status,
            attempt_count=row.attempt_count,
            succeeded=False,
        )
        for row in due
    ]


@router.post(
    "/emr/retry-due",
    response_model=EmrRetryDrainResponse,
)
async def drain_emr_retry_queue(
    body: EmrRetryRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> EmrRetryDrainResponse:
    """Process the rows currently due for retry, up to `limit`.

    For each due row:
      1. Look up the source session + the latest note + decrypt the
         patient identifier (so the FHIR serializer has what it
         originally had)
      2. Re-run the connector via `retry_row`
      3. Audit the outcome (SENT or FAILED) tied to the SAME
         write_back_id as the original attempt

    Rows whose session / note can't be located get skipped (counted
    in `candidates` but not in `attempted`); the row stays in failed
    state with scheduled_at still set, so the next drain pass will
    retry the lookup as well.
    """
    due_rows = await emr_service.list_due_for_retry(db, limit=body.limit)

    sent = 0
    still_failed = 0
    attempted = 0
    results: list[EmrRetryRowResult] = []

    for row in due_rows:
        # Pull the session — required for clinician_id (FHIR author)
        # + the encrypted identifier. We don't trust the row's
        # connector key beyond what's in the registry; retry_row
        # re-resolves via the registry.
        session = await db.get(SessionModel, row.session_id)
        if session is None:
            logger.warning(
                "emr retry: skipping row=%s — source session missing",
                row.id,
            )
            results.append(
                EmrRetryRowResult(
                    write_back_id=str(row.id),
                    session_id=str(row.session_id),
                    connector=row.connector,
                    status=row.status,
                    attempt_count=row.attempt_count,
                    succeeded=False,
                )
            )
            continue

        note = await get_latest_note(str(row.session_id), db)
        if note is None:
            logger.warning(
                "emr retry: skipping row=%s — no note for session",
                row.id,
            )
            results.append(
                EmrRetryRowResult(
                    write_back_id=str(row.id),
                    session_id=str(row.session_id),
                    connector=row.connector,
                    status=row.status,
                    attempt_count=row.attempt_count,
                    succeeded=False,
                )
            )
            continue

        identifier_plain: Optional[str] = None
        if session.external_reference_id_encrypted is not None:
            try:
                identifier_plain = decrypt_str(
                    session.external_reference_id_encrypted
                )
            except Exception:
                logger.warning(
                    "emr retry: identifier decrypt failed session=%s — "
                    "retrying without",
                    row.session_id,
                )

        attempted += 1
        try:
            updated = await emr_service.retry_row(
                row,
                note,
                author_user_id=str(session.clinician_id),
                external_reference_id=identifier_plain,
                db=db,
            )
        except KeyError:
            # Connector key disappeared from the registry between
            # original send + this retry. Leave the row alone; an
            # operator will need to re-register.
            logger.warning(
                "emr retry: connector=%s no longer registered (row=%s)",
                row.connector, row.id,
            )
            results.append(
                EmrRetryRowResult(
                    write_back_id=str(row.id),
                    session_id=str(row.session_id),
                    connector=row.connector,
                    status=row.status,
                    attempt_count=row.attempt_count,
                    succeeded=False,
                )
            )
            continue

        succeeded = updated.status == "sent"
        if succeeded:
            sent += 1
            await write_audit(
                updated.session_id,
                AuditEventType.EMR_WRITE_BACK_SENT,
                actor_id=str(user.user_id),
                write_back_id=str(updated.id),
                connector=updated.connector,
                external_id=updated.external_id,
                attempt_count=updated.attempt_count,
            )
        else:
            still_failed += 1
            await write_audit(
                updated.session_id,
                AuditEventType.EMR_WRITE_BACK_FAILED,
                actor_id=str(user.user_id),
                write_back_id=str(updated.id),
                connector=updated.connector,
                error_reason=updated.error_reason or "unknown",
                attempt_count=updated.attempt_count,
            )

        results.append(
            EmrRetryRowResult(
                write_back_id=str(updated.id),
                session_id=str(updated.session_id),
                connector=updated.connector,
                status=updated.status,
                attempt_count=updated.attempt_count,
                succeeded=succeeded,
            )
        )

    await db.commit()
    return EmrRetryDrainResponse(
        candidates=len(due_rows),
        attempted=attempted,
        sent=sent,
        still_failed=still_failed,
        results=results,
    )
