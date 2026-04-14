"""Quebec Law 25 privacy compliance endpoints.

Provides data subject access requests (DSAR), data export,
account deletion, and consent history for authenticated users.
Every endpoint operates on the authenticated user's own data only.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import NoteVersionModel, PilotMetricsModel, SessionModel
from app.core.s3 import AUDIO_BUCKET, FRAMES_BUCKET, get_s3_client
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user

logger = logging.getLogger("aurion.privacy")

router = APIRouter(prefix="/privacy", tags=["privacy"])

# ── Consent event types used for filtering ───────────────────────────────

_CONSENT_EVENT_TYPES = frozenset({
    "consent_confirmed",
    "biometric_consent_confirmed",
    "voice_enrollment_complete",
})


# ── Response Schemas ─────────────────────────────────────────────────────

class AccountInfo(BaseModel):
    user_id: str
    email: str
    role: str


class SessionSummary(BaseModel):
    id: str
    specialty: str
    state: str
    consent_confirmed: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class NoteVersionSummary(BaseModel):
    id: str
    session_id: str
    version: int
    stage: int
    provider_used: str
    specialty: str
    completeness_score: float
    is_approved: bool
    created_at: str


class MetricSummary(BaseModel):
    id: str
    session_id: str
    specialty: str | None
    template_section_completeness: float | None
    citation_traceability_rate: float | None
    conflict_rate: float | None
    low_confidence_frame_rate: float | None
    stage1_latency_ms: int | None
    stage2_latency_ms: int | None
    session_completeness: bool
    created_at: str


class DSARResponse(BaseModel):
    """Full data subject access request response."""
    account_info: AccountInfo
    sessions: list[SessionSummary]
    notes: list[NoteVersionSummary]
    metrics: list[MetricSummary]
    consents: list[dict[str, Any]]
    voice_enrollment_status: str = Field(
        description="One of: enrolled, not_enrolled, deleted"
    )
    generated_at: str


class DeletionResult(BaseModel):
    """Summary of what was deleted vs retained."""
    deleted: dict[str, int]
    retained: dict[str, str]


class ConsentEvent(BaseModel):
    session_id: str
    event_type: str
    event_timestamp: str
    extra: dict[str, Any] = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_user_sessions(
    db: AsyncSession, clinician_id: uuid.UUID
) -> list[SessionModel]:
    result = await db.execute(
        select(SessionModel).where(SessionModel.clinician_id == clinician_id)
    )
    return list(result.scalars().all())


async def _get_note_versions_for_sessions(
    db: AsyncSession, session_ids: list[uuid.UUID]
) -> list[NoteVersionModel]:
    if not session_ids:
        return []
    result = await db.execute(
        select(NoteVersionModel).where(NoteVersionModel.session_id.in_(session_ids))
    )
    return list(result.scalars().all())


async def _get_metrics_for_clinician(
    db: AsyncSession, clinician_id: uuid.UUID
) -> list[PilotMetricsModel]:
    result = await db.execute(
        select(PilotMetricsModel).where(PilotMetricsModel.clinician_id == clinician_id)
    )
    return list(result.scalars().all())


async def _get_audit_events_for_sessions(
    session_ids: list[uuid.UUID],
) -> list[dict[str, Any]]:
    """Retrieve all audit events across the user's sessions."""
    audit = get_audit_log_service()
    all_events: list[dict[str, Any]] = []
    for sid in session_ids:
        events = await audit.get_session_events(sid)
        all_events.extend(events)
    return all_events


def _filter_consent_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e for e in events if e.get("event_type") in _CONSENT_EVENT_TYPES
    ]


def _determine_voice_enrollment_status(events: list[dict[str, Any]]) -> str:
    """Determine voice enrollment status from audit log events.

    Returns 'enrolled', 'deleted', or 'not_enrolled'.
    """
    enrolled = False
    deleted = False
    for e in sorted(events, key=lambda x: x.get("event_timestamp", "")):
        etype = e.get("event_type", "")
        if etype == "voice_enrollment_complete":
            enrolled = True
            deleted = False
        elif etype == "voice_enrollment_deleted":
            deleted = True
            enrolled = False

    if deleted:
        return "deleted"
    if enrolled:
        return "enrolled"
    return "not_enrolled"


def _session_to_summary(s: SessionModel) -> SessionSummary:
    from app.core.types import SessionState

    return SessionSummary(
        id=str(s.id),
        specialty=s.specialty,
        state=s.state.value if isinstance(s.state, SessionState) else str(s.state),
        consent_confirmed=s.consent_confirmed,
        created_at=s.created_at.isoformat() if s.created_at else "",
        updated_at=s.updated_at.isoformat() if s.updated_at else "",
    )


def _note_to_summary(n: NoteVersionModel) -> NoteVersionSummary:
    return NoteVersionSummary(
        id=str(n.id),
        session_id=str(n.session_id),
        version=n.version,
        stage=n.stage,
        provider_used=n.provider_used,
        specialty=n.specialty,
        completeness_score=n.completeness_score,
        is_approved=n.is_approved,
        created_at=n.created_at.isoformat() if n.created_at else "",
    )


def _metric_to_summary(m: PilotMetricsModel) -> MetricSummary:
    return MetricSummary(
        id=str(m.id),
        session_id=str(m.session_id),
        specialty=m.specialty,
        template_section_completeness=m.template_section_completeness,
        citation_traceability_rate=m.citation_traceability_rate,
        conflict_rate=m.conflict_rate,
        low_confidence_frame_rate=m.low_confidence_frame_rate,
        stage1_latency_ms=m.stage1_latency_ms,
        stage2_latency_ms=m.stage2_latency_ms,
        session_completeness=m.session_completeness,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


async def _build_dsar_payload(
    user: CurrentUser,
    db: AsyncSession,
) -> dict[str, Any]:
    """Build the complete DSAR payload for the authenticated user."""
    sessions = await _get_user_sessions(db, user.user_id)
    session_ids = [s.id for s in sessions]

    notes = await _get_note_versions_for_sessions(db, session_ids)
    metrics = await _get_metrics_for_clinician(db, user.user_id)
    all_events = await _get_audit_events_for_sessions(session_ids)
    consent_events = _filter_consent_events(all_events)
    voice_status = _determine_voice_enrollment_status(all_events)

    return DSARResponse(
        account_info=AccountInfo(
            user_id=str(user.user_id),
            email=user.email,
            role=user.role.value,
        ),
        sessions=[_session_to_summary(s) for s in sessions],
        notes=[_note_to_summary(n) for n in notes],
        metrics=[_metric_to_summary(m) for m in metrics],
        consents=consent_events,
        voice_enrollment_status=voice_status,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    ).model_dump()


def _purge_s3_objects_for_sessions(session_ids: list[uuid.UUID]) -> int:
    """Delete all S3 objects belonging to the given sessions.

    Scans both audio and frames buckets for objects keyed by session ID.
    Returns the total number of objects deleted.
    """
    s3 = get_s3_client()
    deleted_count = 0

    for bucket in (AUDIO_BUCKET, FRAMES_BUCKET):
        for sid in session_ids:
            prefix = str(sid)
            try:
                paginator = s3.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                    objects = page.get("Contents", [])
                    if not objects:
                        continue
                    keys = [{"Key": obj["Key"]} for obj in objects]
                    s3.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": keys, "Quiet": True},
                    )
                    deleted_count += len(keys)
            except Exception:
                # S3 errors during purge are logged but do not block deletion
                logger.warning(
                    "S3 purge error for session=%s bucket=%s",
                    str(sid),
                    bucket,
                    exc_info=True,
                )

    return deleted_count


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/my-data", response_model=DSARResponse)
async def get_my_data(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Data Subject Access Request (DSAR) — Quebec Law 25.

    Returns all personal data held for the authenticated user:
    account info, sessions, note versions, pilot metrics,
    consent events, and voice enrollment status.
    """
    return await _build_dsar_payload(user, db)


@router.get("/export")
async def export_my_data(
    format: str = Query(default="json", regex="^json$"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Machine-readable export of all personal data.

    Supports JSON format. Uses streaming for large datasets.
    Quebec Law 25 requires data portability in a structured format.
    """
    payload = await _build_dsar_payload(user, db)
    json_bytes = json.dumps(payload, indent=2, default=str).encode("utf-8")

    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aurion-data-export-{user.user_id}.json"'
            ),
        },
    )


@router.delete("/my-account", response_model=DeletionResult)
async def delete_my_account(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeletionResult:
    """Full account deletion — Quebec Law 25 right to erasure.

    Deletes:
      - All sessions (cascades to note_versions via DB)
      - All pilot metrics for the user
      - All remaining S3 objects for the user's sessions

    Retained:
      - Audit log entries are immutable and cannot be deleted.
        An ``account_deleted`` event is appended recording what was removed.
        Audit logs are retained for 7 years per Quebec regulatory requirements.
    """
    # 1. Gather session IDs before deletion
    sessions = await _get_user_sessions(db, user.user_id)
    session_ids = [s.id for s in sessions]
    session_count = len(sessions)

    # 2. Count note versions before deletion
    notes = await _get_note_versions_for_sessions(db, session_ids)
    note_count = len(notes)

    # 3. Delete note versions
    if session_ids:
        await db.execute(
            delete(NoteVersionModel).where(
                NoteVersionModel.session_id.in_(session_ids)
            )
        )

    # 4. Count and delete pilot metrics
    metrics = await _get_metrics_for_clinician(db, user.user_id)
    metric_count = len(metrics)
    await db.execute(
        delete(PilotMetricsModel).where(
            PilotMetricsModel.clinician_id == user.user_id
        )
    )

    # 5. Delete sessions
    await db.execute(
        delete(SessionModel).where(SessionModel.clinician_id == user.user_id)
    )

    # 6. Purge S3 objects
    s3_deleted = _purge_s3_objects_for_sessions(session_ids)

    # 7. Flush DB changes (commit happens in get_db dependency)
    await db.flush()

    # 8. Write account_deleted audit event — audit log is append-only,
    #    we record what was deleted without removing any existing entries
    audit = get_audit_log_service()
    for sid in session_ids:
        await audit.write_event(
            session_id=sid,
            event_type="account_deleted",
            clinician_id=str(user.user_id),
            deleted_sessions=session_count,
            deleted_note_versions=note_count,
            deleted_pilot_metrics=metric_count,
            deleted_s3_objects=s3_deleted,
            retention_note="Audit logs pseudonymized, retained 7 years for compliance",
        )

    # If the user had no sessions, still log the deletion at account level
    if not session_ids:
        await audit.write_event(
            session_id=f"account-{user.user_id}",
            event_type="account_deleted",
            clinician_id=str(user.user_id),
            deleted_sessions=0,
            deleted_note_versions=0,
            deleted_pilot_metrics=0,
            deleted_s3_objects=0,
            retention_note="Audit logs pseudonymized, retained 7 years for compliance",
        )

    logger.info(
        "Account deleted: user=%s sessions=%d notes=%d metrics=%d s3=%d",
        str(user.user_id),
        session_count,
        note_count,
        metric_count,
        s3_deleted,
    )

    return DeletionResult(
        deleted={
            "sessions": session_count,
            "note_versions": note_count,
            "pilot_metrics": metric_count,
            "s3_objects": s3_deleted,
        },
        retained={
            "audit_logs": "pseudonymized, retained 7 years for compliance",
        },
    )


@router.get("/consents", response_model=list[ConsentEvent])
async def get_consent_history(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConsentEvent]:
    """Return all consent events for the authenticated user.

    Includes: consent_confirmed, biometric_consent_confirmed,
    and voice_enrollment_complete events extracted from the
    immutable audit log.
    """
    sessions = await _get_user_sessions(db, user.user_id)
    session_ids = [s.id for s in sessions]

    all_events = await _get_audit_events_for_sessions(session_ids)
    consent_events = _filter_consent_events(all_events)

    result: list[ConsentEvent] = []
    for e in consent_events:
        # Extract known fields, put everything else in extra
        known_keys = {"session_id", "event_type", "event_timestamp", "event_id"}
        extra = {k: v for k, v in e.items() if k not in known_keys}
        result.append(
            ConsentEvent(
                session_id=e.get("session_id", ""),
                event_type=e.get("event_type", ""),
                event_timestamp=e.get("event_timestamp", ""),
                extra=extra,
            )
        )

    return result
