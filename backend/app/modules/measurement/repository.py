"""Persistence for on-device visual measurements (#63).

Stores the structured, physician-confirmed ``MeasurementCitation`` the
iPhone computes (never raw frames). Idempotent on (session_id,
measurement_id) so a retried POST doesn't duplicate a row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import MeasurementCitationModel
from app.core.types import MeasurementCitation


async def get_by_measurement_id(
    db: AsyncSession, session_id: uuid.UUID, measurement_id: str
) -> MeasurementCitationModel | None:
    result = await db.execute(
        select(MeasurementCitationModel).where(
            MeasurementCitationModel.session_id == session_id,
            MeasurementCitationModel.measurement_id == measurement_id,
        )
    )
    return result.scalar_one_or_none()


async def persist(
    db: AsyncSession, session_id: uuid.UUID, citation: MeasurementCitation
) -> tuple[MeasurementCitationModel, bool]:
    """Idempotent insert keyed on (session_id, measurement_id). Returns
    ``(row, created)`` — a re-POST of the same id returns the existing row
    untouched (so the audit trail isn't double-written). The caller commits.

    ``certified_measurement`` is forced False regardless of input — the
    "approximate, not certified" disclaimer is structural (design §6); a
    client can never persist a "certified" measurement.
    """
    existing = await get_by_measurement_id(db, session_id, citation.measurement_id)
    if existing is not None:
        return existing, False

    row = MeasurementCitationModel(
        session_id=session_id,
        measurement_id=citation.measurement_id,
        frame_id=citation.frame_id,
        kind=citation.kind,
        value=citation.value,
        unit=citation.unit,
        method=citation.method,
        confidence=citation.confidence,
        confidence_reason=citation.confidence_reason,
        scale_source=citation.scale_source,
        masking_status=citation.masking_status,
        physician_confirmed=citation.physician_confirmed,
        provider_used=citation.provider_used,
        model_version=citation.model_version,
        certified_measurement=False,
    )
    db.add(row)
    await db.flush()
    return row, True


async def list_for_session(
    db: AsyncSession, session_id: uuid.UUID
) -> list[MeasurementCitationModel]:
    result = await db.execute(
        select(MeasurementCitationModel)
        .where(MeasurementCitationModel.session_id == session_id)
        .order_by(MeasurementCitationModel.created_at)
    )
    return list(result.scalars().all())
