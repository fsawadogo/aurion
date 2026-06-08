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
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.database import get_db
from app.core.models import (
    NoteVersionModel,
    PilotMetricsModel,
    SessionModel,
    TranscriptModel,
)
from app.core.s3 import AUDIO_BUCKET, EVAL_BUCKET, FRAMES_BUCKET, get_s3_client
from app.modules.audit_log.service import get_audit_log_service
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.cleanup.service import _evidence_prefix
from app.modules.session.service import _SESSION_CHILD_MODELS

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
        generated_at=utcnow().isoformat(timespec="milliseconds"),
    ).model_dump()


def _purge_session_prefix(s3, bucket: str, prefix: str) -> int:
    """Delete every S3 object under ``s3://{bucket}/{prefix}``.

    Returns the count of objects deleted. Errors are logged and
    swallowed — account deletion is best-effort against S3 because the
    audit log + DB rows are the authoritative record of what was
    removed; a failed S3 purge gets reconciled by the bucket TTL
    policy and the next compliance sweep.
    """
    deleted = 0
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
            deleted += len(keys)
    except Exception:
        logger.warning(
            "S3 purge error: bucket=%s prefix=%s",
            bucket,
            prefix,
            exc_info=True,
        )
    return deleted


def _purge_s3_objects_for_sessions(session_ids: list[uuid.UUID]) -> int:
    """Delete all S3 media belonging to the given sessions.

    Object keys are *kind-prefixed*, never bare session UUIDs, so the
    purge has to target each real prefix in each bucket that holds it:

        AUDIO_BUCKET   audio/{sid}/{uuid}.wav
        FRAMES_BUCKET  frames/{sid}/{ts}.jpg
                       clips/{sid}/{clip_id}.mp4
                       screen_frames/{sid}/{ts}.jpg
        EVAL_BUCKET    frames/{sid}/…, clips/{sid}/…, screen_frames/{sid}/…

    ``list_objects_v2`` ``Prefix`` is a literal leading match, so the
    earlier code's bare ``str(sid)`` prefix matched nothing and deleted
    nothing. The eval bucket additionally holds the frames/clips copied
    out for the eval team and — unlike the audio/frames buckets — has no
    lifecycle/TTL, so an erasure request must reach it explicitly or that
    media survives forever (Quebec Law 25 right to erasure).

    All prefixes are session-UUID-scoped — not PHI. Per-(bucket, prefix)
    errors are swallowed inside ``_purge_session_prefix``; the returned
    count reflects only objects actually deleted, so the
    ``deleted_s3_objects`` audit figure stays truthful even on a partial
    S3 failure.

    Returns the total number of objects deleted across every
    (bucket, prefix, session) combination.
    """
    s3 = get_s3_client()

    deleted = 0
    for sid in session_ids:
        sid_str = str(sid)

        # Audio bucket: raw recordings only.
        deleted += _purge_session_prefix(s3, AUDIO_BUCKET, f"audio/{sid_str}/")

        # Visual evidence lives in BOTH the frames bucket (working copies)
        # and the eval bucket (migrated long-term copies). The clip prefix
        # is reused from cleanup so the purge + cleanup paths can't drift.
        # The frame + screen prefixes are spelled out here on purpose:
        # cleanup's ``_evidence_prefix("frame", …)`` still returns the stale
        # flat ``{sid}/`` baseline (it predates the ``frames/{sid}/`` layout
        # the upload path now writes — see app/api/v1/frames.py), and
        # cleanup exposes no screen-frame prefix at all.
        visual_prefixes = (
            f"frames/{sid_str}/",
            _evidence_prefix("clip", sid_str),  # clips/{sid}/
            f"screen_frames/{sid_str}/",
        )
        for bucket in (FRAMES_BUCKET, EVAL_BUCKET):
            for prefix in visual_prefixes:
                deleted += _purge_session_prefix(s3, bucket, prefix)

    return deleted


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
      - All sessions and every row keyed to them. The session-child
        rows are erased via the SAME ``_SESSION_CHILD_MODELS`` enumeration
        the per-session discard path uses (``session.service``) so the two
        erasure paths can't drift. That set covers the full verbatim
        ``transcripts`` text (PHI), note_versions, pilot_metrics,
        stage2_jobs, eval_scores, and eval_assignments. (#344 — transcripts
        were previously orphaned in Postgres because ``transcripts.session_id``
        is a bare PK with no ON DELETE CASCADE.)
      - All pilot metrics for the user — additionally swept by
        ``clinician_id`` to catch metrics-but-no-sessions rows the
        session-scoped delete can't see.
      - All remaining S3 media for the user's sessions, across every
        bucket and kind-prefix: raw audio (audio/), plus frames/, clips/,
        and screen_frames/ in BOTH the frames bucket and the no-TTL eval
        bucket. The real deleted count is recorded on the audit row.

    Retained:
      - Audit log entries are immutable and cannot be deleted.
        An ``account_deleted`` event is appended recording what was removed.
        Audit logs are retained for 7 years per Quebec regulatory requirements.
    """
    # 1. Gather session IDs before deletion
    sessions = await _get_user_sessions(db, user.user_id)
    session_ids = [s.id for s in sessions]
    session_count = len(sessions)

    # 2. Pre-count note versions + pilot metrics for the audit row +
    #    response. Counted BEFORE any delete so the figures are the real
    #    totals (the session-scoped sweep in step 3 removes the rows).
    notes = await _get_note_versions_for_sessions(db, session_ids)
    note_count = len(notes)
    metrics = await _get_metrics_for_clinician(db, user.user_id)
    metric_count = len(metrics)

    # 3. Delete EVERY session-child row by session_id, reusing the
    #    authoritative ``_SESSION_CHILD_MODELS`` list from session.service
    #    so account-erasure and per-session discard can't drift (#344).
    #    This is what removes the verbatim ``transcripts`` rows (full
    #    transcript text = PHI) that were previously orphaned — the bare
    #    ``transcripts.session_id`` PK has no FK/ON DELETE CASCADE to
    #    ``sessions``. Covers transcripts, note_versions, pilot_metrics,
    #    stage2_jobs, eval_scores, eval_assignments.
    child_counts: dict[str, int] = {}
    if session_ids:
        for model in _SESSION_CHILD_MODELS:
            result = await db.execute(
                delete(model).where(model.session_id.in_(session_ids))
            )
            child_counts[model.__tablename__] = result.rowcount or 0
    transcript_count = child_counts.get(TranscriptModel.__tablename__, 0)

    # 4. Sweep any pilot metrics not keyed to a surviving session.
    #    Pilot metrics carry both ``clinician_id`` and ``session_id``; the
    #    clinician-scoped delete catches metrics-but-no-sessions rows
    #    (e.g. a session already discarded) that the session_id sweep in
    #    step 3 misses. Idempotent when step 3 already removed them.
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
    #    we record what was deleted without removing any existing
    #    entries. One event per session so per-session compliance
    #    queries still find it; if the user had no sessions we still
    #    emit one row keyed by ``account-{user_id}`` so the deletion
    #    isn't invisible. Counters are the *real* totals in both
    #    paths — earlier code hardcoded zeros in the no-sessions
    #    branch, which silently under-reported pilot_metrics
    #    deletions for users with metrics-but-no-sessions.
    audit_targets: list[str | uuid.UUID] = (
        list(session_ids) if session_ids else [f"account-{user.user_id}"]
    )
    audit_kwargs: dict[str, Any] = dict(
        clinician_id=str(user.user_id),
        deleted_sessions=session_count,
        deleted_note_versions=note_count,
        deleted_pilot_metrics=metric_count,
        deleted_transcripts=transcript_count,
        deleted_s3_objects=s3_deleted,
        retention_note="Audit logs pseudonymized, retained 7 years for compliance",
    )
    for target in audit_targets:
        await write_audit(target, AuditEventType.ACCOUNT_DELETED, **audit_kwargs)

    logger.info(
        "Account deleted: user=%s sessions=%d notes=%d metrics=%d "
        "transcripts=%d s3=%d",
        str(user.user_id),
        session_count,
        note_count,
        metric_count,
        transcript_count,
        s3_deleted,
    )

    return DeletionResult(
        deleted={
            "sessions": session_count,
            "note_versions": note_count,
            "pilot_metrics": metric_count,
            "transcripts": transcript_count,
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
