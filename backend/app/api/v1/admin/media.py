"""Admin "Captured Media" endpoints — windowed media retention review (#338).

Two surfaces, both gated behind ``feature_flags.media_review_retention_enabled``
AND a role check (the feature is PHI-sensitive — raw audio is unmasked patient
speech, so it ships dark and is locked to the eval/compliance/admin surface):

  1. ``GET /api/v1/admin/media`` — list sessions whose raw media is still inside
     the retention window. ADMIN, EVAL_TEAM, or COMPLIANCE_OFFICER. The list
     carries NO patient identifier — only the physician name, session timing,
     visit/encounter context, state, media availability, and a retention
     countdown. Compliance officers get the list (and, via the audit log
     viewer, the download trail) but never a download URL.

  2. ``GET /api/v1/admin/media/{session_id}/download-urls`` — presigned download
     URLs for the session's retained audio + clips. ADMIN or EVAL_TEAM ONLY —
     COMPLIANCE_OFFICER is view-only and gets a 403. Every successful call
     emits ``EVIDENCE_DOWNLOADED`` (PHI-free counts only).

Retention model (decided upstream): media is kept for the full
``pipeline.media_review_retention_days`` window and removed only by the S3
lifecycle TTL or a Law 25 erasure — so a session stays downloadable across its
whole window regardless of approval/export state. The per-session S3 list is
the source of truth for *current* availability, so a session that has already
been purged simply reports ``has_audio=false`` / ``clip_count=0`` rather than
being hidden.

No business logic lives in the route bodies — listing + presign mechanics are
module-level helpers. Pilot scale is tiny (3-5 clinicians), so a bounded
per-session S3 list is acceptable; the page-size cap bounds the number of
list calls per request and any per-session truncation is logged, never
silently dropped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_session_or_404, write_audit
from app.api.v1.admin._shared import resolve_clinician_names
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import SessionModel
from app.core.s3 import (
    AUDIO_BUCKET,
    DEFAULT_EVIDENCE_TTL_SECONDS,
    FRAMES_BUCKET,
    generate_presigned_evidence_url,
    get_s3_client,
)
from app.core.types import SessionState, UserRole
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_config

logger = logging.getLogger("aurion.admin.media")

router = APIRouter(prefix="/admin", tags=["admin"])

# Evidence kind carried on the EVIDENCE_DOWNLOADED audit row — a fixed,
# PHI-free string (parallels EVIDENCE_REPLAYED's "audio"/"clip"/"frame").
_EVIDENCE_KIND = "session_media"

# States that indicate the session's raw media reached S3 (audio uploaded +
# transcribed). Pre-review states (IDLE … PROCESSING_STAGE1) have no retained
# media to surface; PURGED / STAGE1_FAILED_NO_AUDIO are terminal "nothing to
# download" states and are excluded from the list. EXPORTED is INCLUDED — per
# the retention model a session stays downloadable across its whole window
# regardless of export/approval state; the per-session S3 list reports the
# true current availability.
_MEDIA_BEARING_STATES: frozenset[SessionState] = frozenset(
    {
        SessionState.AWAITING_REVIEW,
        SessionState.PROCESSING_STAGE2,
        SessionState.REVIEW_COMPLETE,
        SessionState.EXPORTED,
    }
)

# Hard cap on objects listed per S3 prefix per session. Pilot clips-per-session
# is small; this is a paranoia ceiling so one runaway session can't make the
# list endpoint walk thousands of keys. If a prefix truncates at this bound we
# LOG it and report the bounded count — never silently drop the overflow.
_MAX_OBJECTS_PER_PREFIX = 500


# ── Schemas ─────────────────────────────────────────────────────────────────


class MediaSessionItem(BaseModel):
    """One row in the Captured Media list. Carries NO patient identifier."""

    session_id: str
    physician_name: str
    started_at: str
    visit_type: Optional[str] = None
    context_label: Optional[str] = None
    encounter_type: str
    state: str
    has_audio: bool
    clip_count: int
    retention_expires_at: str


class MediaListResponse(BaseModel):
    items: list[MediaSessionItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    retention_days: int


class ClipDownloadUrl(BaseModel):
    clip_id: str
    url: str


class MediaDownloadUrlsResponse(BaseModel):
    audio_url: Optional[str] = None
    clips: list[ClipDownloadUrl] = Field(default_factory=list)
    expires_in: int


# ── Helpers ─────────────────────────────────────────────────────────────────


def _raise_flag_off() -> None:
    """403 when the windowed media-retention feature is disabled."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Media review retention is not enabled.",
    )


def _retention_window_start(retention_days: int) -> datetime:
    """UTC cut-off: sessions started before this are past the window."""
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


def _expires_at(started_at: Optional[datetime], retention_days: int) -> str:
    """ISO-8601 retention expiry = started_at + retention window. Empty
    string when the session has no timestamp (shouldn't happen — created_at
    is non-nullable — but stays defensive)."""
    if started_at is None:
        return ""
    return (started_at + timedelta(days=retention_days)).isoformat()


def _list_prefix_keys(bucket: str, prefix: str) -> list[str]:
    """List up to ``_MAX_OBJECTS_PER_PREFIX`` keys under ``prefix``.

    Returns [] on any S3 error (degrade — a transient S3 hiccup must not 500
    the whole list). LOGs (truncated session-scoped prefix only) when the
    listing is capped so the cap is never silent.
    """
    client = get_s3_client()
    try:
        response = client.list_objects_v2(
            Bucket=bucket, Prefix=prefix, MaxKeys=_MAX_OBJECTS_PER_PREFIX
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning(
            "Media listing failed: bucket=%s prefix=%s: %s",
            bucket,
            prefix[:18],
            exc,
        )
        return []
    keys = [
        obj["Key"]
        for obj in response.get("Contents", [])
        if isinstance(obj.get("Key"), str)
    ]
    if response.get("IsTruncated"):
        logger.warning(
            "Media listing capped at %d objects: bucket=%s prefix=%s "
            "(reporting bounded count; not silently truncating)",
            _MAX_OBJECTS_PER_PREFIX,
            bucket,
            prefix[:18],
        )
    return keys


def _media_availability(session_id: str) -> tuple[bool, int]:
    """Report (has_audio, clip_count) for a session via bounded S3 lists."""
    audio_keys = _list_prefix_keys(AUDIO_BUCKET, f"audio/{session_id}/")
    clip_keys = _list_prefix_keys(FRAMES_BUCKET, f"clips/{session_id}/")
    return (len(audio_keys) > 0, len(clip_keys))


def _clip_id_from_key(key: str) -> str:
    """Extract ``{clip_id}`` from ``clips/{session_id}/{clip_id}.mp4``."""
    filename = key.rsplit("/", 1)[-1]
    if filename.endswith(".mp4"):
        return filename[: -len(".mp4")]
    return filename


def _resolve_download_urls(
    session_id: str,
) -> tuple[Optional[str], list[ClipDownloadUrl], int, int]:
    """Presign download URLs for a session's retained audio + clips.

    Returns ``(audio_url, clips, audio_count, clip_count)``. Individual
    presign failures degrade that entry to null/skip rather than raising —
    one bad object never sinks the whole response. The signed URLs keep the
    ca-central-1 SigV4 host and the default 1h TTL (NOT widened). Neither the
    S3 keys nor the signed URLs are ever logged.
    """
    audio_keys = _list_prefix_keys(AUDIO_BUCKET, f"audio/{session_id}/")
    clip_keys = _list_prefix_keys(FRAMES_BUCKET, f"clips/{session_id}/")

    audio_url: Optional[str] = None
    if audio_keys:
        try:
            audio_url = generate_presigned_evidence_url(
                audio_keys[0], bucket=AUDIO_BUCKET
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Audio download presign failed: session=%s: %s",
                session_id[:12],
                exc,
            )
            audio_url = None

    clips: list[ClipDownloadUrl] = []
    for key in clip_keys:
        try:
            url = generate_presigned_evidence_url(key, bucket=FRAMES_BUCKET)
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Clip download presign failed: session=%s: %s",
                session_id[:12],
                exc,
            )
            continue
        clips.append(ClipDownloadUrl(clip_id=_clip_id_from_key(key), url=url))

    return audio_url, clips, len(audio_keys), len(clip_keys)


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/media", response_model=MediaListResponse)
async def list_captured_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(
        require_role(
            UserRole.ADMIN,
            UserRole.EVAL_TEAM,
            UserRole.COMPLIANCE_OFFICER,
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> MediaListResponse:
    """List sessions with retained media inside the retention window.

    ADMIN, EVAL_TEAM, or COMPLIANCE_OFFICER. Flag-gated: 403 when
    ``media_review_retention_enabled`` is off (the feature does not exist
    for the client). Selects sessions in a media-bearing state (transcription
    happened) whose ``created_at`` is within ``media_review_retention_days``.
    Each row reports current media availability via a bounded per-session S3
    list. NO patient identifier is included.
    """
    cfg = get_config()
    if not cfg.feature_flags.media_review_retention_enabled:
        _raise_flag_off()

    retention_days = cfg.pipeline.media_review_retention_days
    window_start = _retention_window_start(retention_days)

    base = (
        select(SessionModel)
        .where(SessionModel.state.in_(_MEDIA_BEARING_STATES))
        .where(SessionModel.created_at >= window_start)
    )

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar() or 0

    stmt = (
        base.order_by(SessionModel.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    sessions = (await db.execute(stmt)).scalars().all()

    names_by_id = await resolve_clinician_names(
        db, (s.clinician_id for s in sessions)
    )

    items: list[MediaSessionItem] = []
    for s in sessions:
        has_audio, clip_count = _media_availability(str(s.id))
        items.append(
            MediaSessionItem(
                session_id=str(s.id),
                physician_name=names_by_id[str(s.clinician_id)],
                started_at=s.created_at.isoformat() if s.created_at else "",
                visit_type=s.consultation_type,
                context_label=s.encounter_context,
                encounter_type=s.encounter_type,
                state=s.state.value if hasattr(s.state, "value") else str(s.state),
                has_audio=has_audio,
                clip_count=clip_count,
                retention_expires_at=_expires_at(s.created_at, retention_days),
            )
        )

    return MediaListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        retention_days=retention_days,
    )


@router.get(
    "/media/{session_id}/download-urls",
    response_model=MediaDownloadUrlsResponse,
)
async def get_media_download_urls(
    session_id: str,
    user: CurrentUser = Depends(
        require_role(UserRole.ADMIN, UserRole.EVAL_TEAM)
    ),
    db: AsyncSession = Depends(get_db),
) -> MediaDownloadUrlsResponse:
    """Mint presigned download URLs for a session's retained media.

    ADMIN or EVAL_TEAM ONLY — COMPLIANCE_OFFICER is view-only and is rejected
    with 403 by the role gate. Flag-gated: 403 when the flag is off. Lists the
    session's audio + clips and presigns each (ca-central-1 SigV4, default 1h
    TTL — not widened). Individual presign errors degrade to null/skip rather
    than 500. Emits ``EVIDENCE_DOWNLOADED`` with PHI-free counts only.
    """
    if not get_config().feature_flags.media_review_retention_enabled:
        _raise_flag_off()

    # 404 if the session doesn't exist — keeps the surface honest and avoids
    # minting an audit row for a phantom session.
    session = await get_session_or_404(db, session_id)

    audio_url, clips, audio_count, clip_count = _resolve_download_urls(
        str(session.id)
    )

    await write_audit(
        session.id,
        AuditEventType.EVIDENCE_DOWNLOADED,
        actor_id=str(user.user_id),
        evidence_kind=_EVIDENCE_KIND,
        audio_count=audio_count,
        clip_count=clip_count,
    )

    return MediaDownloadUrlsResponse(
        audio_url=audio_url,
        clips=clips,
        expires_in=DEFAULT_EVIDENCE_TTL_SECONDS,
    )
