"""On-device visual measurement ingest + list (#63).

The iPhone computes a measurement (ARKit/LiDAR or AR goniometer), the
physician confirms it, and the app POSTs the structured ``MeasurementCitation``
here — never raw frames. The backend validates + persists it (idempotent),
writes PHI-free provenance to the audit trail, and gates the whole feature
on ``feature_flags.measurement_enabled`` + the allowed-methods / confidence
floor in AppConfig.

Note-injection (routing a confirmed measurement into the note as a claim)
is a separate slice; this one captures + audits.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, write_audit
from app.api.v1.me import get_current_clinician
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import MeasurementCitationModel
from app.core.types import MeasurementCitation
from app.modules.auth.service import CurrentUser
from app.modules.config.appconfig_client import get_config
from app.modules.measurement import repository as measurement_repo

router = APIRouter(prefix="/me", tags=["me.measurements"])

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


@router.post(
    "/sessions/{session_id}/measurements",
    response_model=MeasurementCitation,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_measurement(
    session_id: uuid.UUID,
    citation: MeasurementCitation,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> MeasurementCitation:
    """Persist a physician-confirmed on-device measurement for the session.

    Idempotent on the citation's ``measurement_id``. Gated by
    ``measurement_enabled`` + the allowed methods + the confidence floor.
    The numeric value is never logged (derived PHI); only PHI-free
    provenance reaches the audit trail.
    """
    await get_owned_session_or_404(db, session_id, user)

    # Path is authoritative for the session; reject a body/path mismatch.
    try:
        body_session = uuid.UUID(citation.session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="citation.session_id is not a valid UUID.",
        ) from exc
    if body_session != session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="citation.session_id does not match the path session_id.",
        )

    cfg = get_config()
    if not cfg.feature_flags.measurement_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Visual measurement is not enabled.",
        )
    if citation.method not in cfg.measurement.methods_allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Measurement method '{citation.method}' is not permitted.",
        )
    if _CONFIDENCE_RANK[citation.confidence] < _CONFIDENCE_RANK[cfg.measurement.min_confidence]:
        raise HTTPException(
            status_code=422,
            detail="Measurement confidence is below the configured floor.",
        )

    row, created = await measurement_repo.persist(db, session_id, citation)
    if created:
        await write_audit(
            session_id,
            AuditEventType.MEASUREMENT_GENERATED,
            measurement_id=row.measurement_id,
            kind=row.kind,
            method=row.method,
            unit=row.unit,
            confidence=row.confidence,
            scale_source=row.scale_source or "",
            masking_status=row.masking_status,
        )
        if row.physician_confirmed:
            await write_audit(
                session_id,
                AuditEventType.MEASUREMENT_REVIEWED,
                measurement_id=row.measurement_id,
                kind=row.kind,
                physician_confirmed=True,
            )
        await db.commit()
    return _to_citation(row)


@router.get(
    "/sessions/{session_id}/measurements",
    response_model=list[MeasurementCitation],
)
async def list_measurements(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> list[MeasurementCitation]:
    """All confirmed measurements captured for the session, oldest first."""
    await get_owned_session_or_404(db, session_id, user)
    rows = await measurement_repo.list_for_session(db, session_id)
    return [_to_citation(r) for r in rows]


def _to_citation(row: MeasurementCitationModel) -> MeasurementCitation:
    return MeasurementCitation(
        measurement_id=row.measurement_id,
        session_id=str(row.session_id),
        frame_id=row.frame_id,
        kind=row.kind,
        value=row.value,
        unit=row.unit,
        method=row.method,
        confidence=row.confidence,
        confidence_reason=row.confidence_reason,
        scale_source=row.scale_source,
        masking_status=row.masking_status,
        physician_confirmed=row.physician_confirmed,
        provider_used=row.provider_used,
        model_version=row.model_version,
    )
