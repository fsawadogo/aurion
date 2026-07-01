"""CRUD service for `schedule_entries` rows — the per-clinician patient
schedule (issue #603, last MVP scope item).

Owner-scoped throughout — every read path filters on `clinician_id` and
every write path takes the caller's id explicitly, so a buggy route layer
above can't leak across clinicians (same posture as `macros.service`).

PHI handling mirrors the `sessions` external-reference-id pipeline: the
patient identifier is validated (fail-closed against name/email/SSN
foot-guns), then stored KMS-encrypted + HMAC-hashed. Plaintext never
lands in a column, a log, or an audit row; it is decrypted only for the
owning clinician's response via `to_response`.

This is NOT a calendar/booking system: `scheduled_for` is a single
optional timestamp with no conflict detection or recurrence, and repeat
entries for the same patient are allowed (a clinician sees patients on
many days).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identifier_hash import hash_identifier
from app.core.kms_encryption import decrypt_str, encrypt_str
from app.core.models import ScheduleEntryModel
from app.core.text_validation import validate_user_text

logger = logging.getLogger("aurion.schedule")

# Identifier gate — same cap the sessions identifier path uses. Fail-closed
# against the common foot-guns (full name, email, SSN) without trying to
# validate every clinic's MRN scheme.
_MAX_IDENTIFIER_LEN = 64
_MAX_NOTE_LEN = 500

# Lifecycle status set + legal transitions. `completed` / `cancelled` are
# terminal — no outgoing edge, so re-opening a finished entry is rejected
# (AC-3). Setting a status to its current value is always a no-op.
_STATUSES: frozenset[str] = frozenset(
    {"scheduled", "in_progress", "completed", "cancelled"}
)
_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"in_progress", "completed", "cancelled"}),
    "in_progress": frozenset({"scheduled", "completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


class ScheduleError(Exception):
    """Service-layer validation/transition error. Route maps to 400/409."""


class ScheduleIdentifierError(ScheduleError):
    """Patient identifier failed the PHI format gate. Route maps to 422
    (and never echoes the rejected value)."""


def validate_patient_identifier(value: str) -> str:
    """Return the cleaned identifier or raise ``ScheduleIdentifierError``.

    Thin wrapper over the shared ``validate_user_text`` core helper (the
    same gate the sessions identifier path uses), re-nouned to
    "identifier" for message parity. The error string is reason-only and
    NEVER contains the rejected value — it may itself be a patient name.
    """
    cleaned = value.strip()
    try:
        validate_user_text(
            cleaned, max_length=_MAX_IDENTIFIER_LEN, reject_full_name=True
        )
    except ValueError as exc:
        raise ScheduleIdentifierError(
            str(exc).replace("text", "identifier", 1)
        ) from None
    return cleaned


def _validate_status(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned not in _STATUSES:
        raise ScheduleError(
            "status must be one of: " + ", ".join(sorted(_STATUSES))
        )
    return cleaned


def _validate_note(note: Optional[str]) -> Optional[str]:
    if note is None:
        return None
    cleaned = note.strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_NOTE_LEN:
        raise ScheduleError(f"note exceeds {_MAX_NOTE_LEN} chars")
    return cleaned


async def list_for_owner(
    clinician_id: uuid.UUID,
    db: AsyncSession,
    status_filter: Optional[str] = None,
) -> list[ScheduleEntryModel]:
    """List the caller's schedule entries, newest-first, optionally
    filtered to a single status."""
    stmt = select(ScheduleEntryModel).where(
        ScheduleEntryModel.clinician_id == clinician_id
    )
    if status_filter:
        stmt = stmt.where(
            ScheduleEntryModel.status == _validate_status(status_filter)
        )
    stmt = stmt.order_by(ScheduleEntryModel.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_owned(
    entry_id: uuid.UUID,
    clinician_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ScheduleEntryModel]:
    """Fetch an entry by id, scoped to the caller. None for non-owner or
    missing row (route maps both to 404 to avoid existence leaks)."""
    stmt = select(ScheduleEntryModel).where(
        ScheduleEntryModel.id == entry_id,
        ScheduleEntryModel.clinician_id == clinician_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_for_owner(
    clinician_id: uuid.UUID,
    patient_identifier: str,
    db: AsyncSession,
    scheduled_for: Optional[datetime] = None,
    note: Optional[str] = None,
) -> ScheduleEntryModel:
    """Insert a new schedule entry. Validates + encrypts the identifier
    before any DB write; raises ``ScheduleIdentifierError`` (route → 422)
    on a PHI foot-gun, ``ScheduleError`` (route → 400) on other bad input."""
    clean_identifier = validate_patient_identifier(patient_identifier)
    clean_note = _validate_note(note)

    row = ScheduleEntryModel(
        id=uuid.uuid4(),
        clinician_id=clinician_id,
        patient_identifier_encrypted=encrypt_str(clean_identifier),
        patient_identifier_hash=hash_identifier(clean_identifier),
        status="scheduled",
        scheduled_for=scheduled_for,
        note=clean_note,
    )
    db.add(row)
    await db.flush()
    return row


async def update_owned(
    row: ScheduleEntryModel,
    db: AsyncSession,
    status: Optional[str] = None,
    scheduled_for: Optional[datetime] = None,
    note: Optional[str] = None,
    clear_scheduled_for: bool = False,
    clear_note: bool = False,
) -> ScheduleEntryModel:
    """Patch fields on an owned entry. Only supplied fields are touched.
    A status change is transition-validated; an illegal transition raises
    ``ScheduleError`` (route → 409)."""
    if status is not None:
        new_status = _validate_status(status)
        current = row.status
        if new_status != current and new_status not in _TRANSITIONS.get(
            current, frozenset()
        ):
            raise ScheduleError(
                f"cannot change status from '{current}' to '{new_status}'"
            )
        row.status = new_status
    if clear_scheduled_for:
        row.scheduled_for = None
    elif scheduled_for is not None:
        row.scheduled_for = scheduled_for
    if clear_note:
        row.note = None
    elif note is not None:
        row.note = _validate_note(note)

    await db.flush()
    return row


async def delete_owned(row: ScheduleEntryModel, db: AsyncSession) -> None:
    """Hard delete. The audit log captures the removal separately so the
    trail is preserved."""
    await db.delete(row)
    await db.flush()


def decrypt_identifier(row: ScheduleEntryModel) -> str:
    """Decrypt the stored patient identifier for the owning clinician's
    response. Only ever called on a row already scoped to the caller."""
    return decrypt_str(row.patient_identifier_encrypted)
