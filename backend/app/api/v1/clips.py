"""Clips API — receive masked video clips from iOS.

POST /api/v1/clips/{session_id} — single masked H.264 clip (no audio
track, audio is stripped iOS-side per the dual-mode plan), persisted to
S3 at ``clips/{session_id}/{clip_id}.mp4`` with KMS server-side
encryption. iOS uploads after stop, before transcription, alongside any
JPEG frames the session captured under the existing frames endpoint.

This is the clip-path sibling to ``/api/v1/frames/{session_id}``. The
auth, owner assertion, fail-closed masking gate, KMS-encrypted S3 write,
audit emission, and response shape mirror that endpoint exactly — the
shared validation surface lives in `_helpers.py` so the DRY contract
holds (§6c).

Per CLAUDE.md: "Raw video frames never leave iOS unmasked — masking
status logged before any upload." The clip path enforces the same gate
via the boolean `masking_confirmed` flag; iOS's `MaskingPipeline.maskClip`
fail-closes any clip where a per-frame face-detect fails, so a `True`
flag reaching this endpoint is the equivalent of the frame path's
four-field MaskingProof shaped down to a single boolean (the per-clip
frame counts ride on `ClipMaskingMetadata` for the audit row).
"""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import (
    assert_masking_confirmed,
    get_owned_session_or_404,
    parse_clip_masking_metadata,
    write_audit,
)
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.schema import VisualEvidenceMode

logger = logging.getLogger("aurion.api.clips")

router = APIRouter(prefix="/clips", tags=["clips"])

# iOS strips the audio track before upload — the multipart body is a
# video-only H.264 MP4. Anything else fails fast at the boundary.
_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"video/mp4"})

# How many characters of the session_id appear in log lines. Matches
# `_session_prefix` truncation pattern from peer services so logs are
# greppable without leaking the full UUID (PHI-adjacent identifier).
_SESSION_LOG_PREFIX_LEN = 8


def _session_log_prefix(session_id: uuid.UUID) -> str:
    return str(session_id)[:_SESSION_LOG_PREFIX_LEN]


class ClipDropReason(StrEnum):
    """Why a cadence clip never reached S3 (#390).

    The first three are per-tick drops inside iOS `emitCadenceClip`; the
    next four are the once-per-session driver-not-started reasons inside
    `startCadenceDriverIfEnabled`; the last is server-side, emitted only by
    the S3 PutObject failure path in `upload_clip`. ``SERVER_S3_PUT_FAILED``
    is server-only — a client beacon claiming it is rejected (a device
    cannot observe a server-side S3 failure).
    """

    # Per-tick (iOS emitCadenceClip)
    RING_EMPTY = "ring_empty"
    MASKING_FAILED = "masking_failed"
    UPLOAD_FAILED = "upload_failed"
    # Driver-not-started (iOS startCadenceDriverIfEnabled)
    CADENCE_SECONDS_ZERO = "cadence_seconds_zero"
    MODE_NOT_CLIPS_OR_HYBRID = "mode_not_clips_or_hybrid"
    VIDEO_SOURCE_NOT_BUILTIN = "video_source_not_builtin"
    CAPTURE_MODE_NOT_MULTIMODAL = "capture_mode_not_multimodal"
    # Server-only (clips.py S3 failure path)
    SERVER_S3_PUT_FAILED = "server_s3_put_failed"


class ClipUploadResponse(BaseModel):
    """Response shape after a successful clip upload.

    Mirrors `FrameUploadResponse` plus the clip-specific fields the iOS
    reviewer needs to render the inline player chip: `clip_id`,
    `duration_ms`, and `evidence_kind` (always `"clip"` for this
    endpoint; included so a polymorphic client can branch on it without
    inspecting URL path).
    """

    session_id: str
    clip_id: str
    s3_key: str
    bytes_uploaded: int
    duration_ms: int
    evidence_kind: str = "clip"


@router.post("/{session_id}", response_model=ClipUploadResponse)
async def upload_clip(
    session_id: uuid.UUID,
    timestamp_ms: int = Form(..., ge=0),
    duration_ms: int = Form(..., ge=1),
    trigger_segment_id: str = Form(..., min_length=1),
    frames_total: int = Form(..., ge=1),
    frames_with_faces: int = Form(..., ge=0),
    masking_confirmed: bool = Form(...),
    # #324 clip cadence floor — how this clip was produced on iOS.
    # "trigger" = extracted at a spoken-keyword trigger timestamp (today's
    # behavior); "cadence" = extracted by the during-recording cadence
    # timer to fill a silent gap. Defaults to "trigger" so existing iOS
    # builds (which don't send the field) keep the prior semantics. Not
    # PHI — a two-value provenance enum, carried into the audit + log for
    # count-only telemetry.
    source: Literal["trigger", "cadence"] = Form("trigger"),
    clip: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClipUploadResponse:
    """Persist a single masked H.264 clip to S3 for Stage 2 enrichment.

    Order of operations matches `upload_frame`:

    1. Auth (handled by `get_current_user` dependency).
    2. Owner assertion: a CLINICIAN can only post to their own sessions.
    3. **Fail-closed masking gate (P0-01)**: reject before any S3 write
       if `masking_confirmed` is False.
    4. Content-type validation: only `video/mp4` is accepted.
    5. KMS-encrypted S3 PutObject under `clips/{session_id}/{clip_id}.mp4`.
       The bucket-level default encryption already enforces KMS; we
       pass `ServerSideEncryption="aws:kms"` for defense-in-depth and
       to match frames.py.
    6. Emit `CLIP_UPLOADED` audit event carrying the masking metadata.
    7. Return `ClipUploadResponse`.
    """
    # 1+2. Owner assertion (this is /clips/ not /me/clips/, mirrors
    # frames.py: clinician routes use `get_owned_session_or_404` which
    # surfaces 404 on cross-clinician access for CLINICIAN role and 403
    # for other non-bypass roles — see `_helpers.assert_owner`).
    await get_owned_session_or_404(db, session_id, user)

    # 3. Fail-closed gate — BEFORE any S3 work.
    assert_masking_confirmed(masking_confirmed)

    # Validate the per-clip masking metadata (faces_blurred defaults to
    # frames_with_faces; the maskClip path fail-closes on partial blur
    # so any clip reaching this endpoint has blurred every detected face).
    masking_metadata = parse_clip_masking_metadata(
        frames_total=frames_total,
        frames_with_faces=frames_with_faces,
    )

    # 4. Content-type validation. Empty/None content_type is treated as
    # invalid — we want an explicit `video/mp4` declaration.
    if clip.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported clip content type: {clip.content_type!r}. "
                f"Expected one of: {sorted(_ALLOWED_CONTENT_TYPES)}."
            ),
        )

    body = await clip.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty clip body")

    # 5. KMS-encrypted S3 PutObject. The clip_id is server-generated so
    # the iOS side never picks the key; this also prevents two clips
    # with the same trigger_segment_id from clobbering each other when
    # the eval team replays a session.
    #
    # #324: embed the trigger-anchor timestamp_ms in the key prefix
    # (zero-padded to 9 digits for lexical sort) so Stage 2 can recover
    # each clip's real timestamp from the key alone. Before this, the key
    # carried no timestamp, so the vision service mis-anchored every clip
    # to trigger_segments[0]; with the prefix it anchors each clip to its
    # nearest transcript segment. Pattern: clips/{sid}/{ts:09d}_{clip_id}.mp4.
    clip_id = uuid.uuid4().hex
    key = f"clips/{session_id}/{timestamp_ms:09d}_{clip_id}.mp4"
    try:
        s3 = get_s3_client()
        s3.put_object(
            Bucket=FRAMES_BUCKET,
            Key=key,
            Body=body,
            ContentType="video/mp4",
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        # Log session prefix + key prefix only — no full UUID, no body.
        logger.error(
            "Clip upload failed: session=%s key=%s error=%s",
            _session_log_prefix(session_id), key[:32], exc,
        )
        # #390: leave a server-side audit row on the S3 failure path.
        # Previously this branch only logged + 500'd, so a clip that the
        # device successfully extracted + masked + sent but that died at the
        # S3 write was invisible after the fact — indistinguishable from a
        # clip the device never attempted. The drop beacon (origin="server")
        # makes the difference greppable in the audit trail. Never let an
        # audit write mask the original upload failure.
        try:
            await write_audit(
                session_id,
                AuditEventType.CLIP_DROPPED,
                reason=ClipDropReason.SERVER_S3_PUT_FAILED.value,
                origin="server",
                timestamp_ms=timestamp_ms,
            )
        except Exception:  # noqa: BLE001 — audit is best-effort here
            logger.exception(
                "Failed to write CLIP_DROPPED audit on S3 failure path: session=%s",
                _session_log_prefix(session_id),
            )
        raise HTTPException(status_code=500, detail=f"Clip upload failed: {exc}")

    # 6. Audit event. Whitelisted kwargs per `ALLOWED_AUDIT_KWARGS` —
    # see `core/audit_events.py:CLIP_UPLOADED`.
    await write_audit(
        session_id,
        AuditEventType.CLIP_UPLOADED,
        timestamp_ms=timestamp_ms,
        bytes=len(body),
        duration_ms=duration_ms,
        trigger_segment_id=trigger_segment_id,
        masking_status="success",
        frames_total=masking_metadata.frames_total,
        frames_with_faces=masking_metadata.frames_with_faces,
        faces_blurred=masking_metadata.faces_blurred,
        source=source,
    )

    logger.info(
        "Clip uploaded: session=%s clip=%s bytes=%d duration_ms=%d source=%s",
        _session_log_prefix(session_id), clip_id[:8], len(body), duration_ms,
        source,
    )

    return ClipUploadResponse(
        session_id=str(session_id),
        clip_id=clip_id,
        s3_key=key,
        bytes_uploaded=len(body),
        duration_ms=duration_ms,
    )


# ── Clip-pipeline drop-site telemetry (#390) ─────────────────────────────────


class ClipTelemetryBeacon(BaseModel):
    """A single iOS clip-pipeline telemetry beacon.

    One model, three ``kind``s (validated per-kind in the handler so an
    invalid combination is a clean 400, not a silently-empty audit row):

    - ``drop``            a once-per-session driver-not-started reason —
                          requires ``reason`` (a client-observable
                          ``ClipDropReason``; the server-only
                          ``server_s3_put_failed`` is rejected).
    - ``summary``         per-session pipeline counters, flushed on stop.
                          Per-tick drops (ring_empty / masking_failed /
                          upload_failed) are reported here in aggregate
                          rather than as a beacon-per-tick, so a noisy
                          camera warm-up can't flood the audit log
                          mid-recording.
    - ``config_snapshot`` the resolved clip config + app build at
                          record-start, so a stale AppConfig snapshot or an
                          old build is visible server-side.

    Every field is non-PHI: enums, counts, tuning values, and a build
    string. No identifiers, no S3 keys, no bodies.
    """

    kind: Literal["drop", "summary", "config_snapshot"]

    # kind="drop"
    reason: ClipDropReason | None = None
    timestamp_ms: int | None = Field(None, ge=0)

    # kind="summary" — counters (all monotonic, non-negative)
    ring_frames_appended: int | None = Field(None, ge=0)
    clips_extracted: int | None = Field(None, ge=0)
    clips_masked: int | None = Field(None, ge=0)
    clips_uploaded: int | None = Field(None, ge=0)
    clips_dropped: int | None = Field(None, ge=0)
    drops_ring_empty: int | None = Field(None, ge=0)
    drops_masking_failed: int | None = Field(None, ge=0)
    drops_upload_failed: int | None = Field(None, ge=0)

    # kind="config_snapshot"
    visual_evidence_mode: VisualEvidenceMode | None = None
    clip_cadence_seconds: int | None = Field(None, ge=0)
    video_capture_fps: float | None = Field(None, ge=0)
    clip_window_ms: int | None = Field(None, ge=0)
    app_build: str | None = Field(None, max_length=64)


class ClipTelemetryResponse(BaseModel):
    session_id: str
    kind: str
    recorded: bool = True


# The summary kwargs that ride into the CLIP_PIPELINE_SUMMARY audit row,
# in declaration order. Only those actually present on the beacon are
# emitted (the audit whitelist accepts a subset).
_SUMMARY_FIELDS: tuple[str, ...] = (
    "ring_frames_appended",
    "clips_extracted",
    "clips_masked",
    "clips_uploaded",
    "clips_dropped",
    "drops_ring_empty",
    "drops_masking_failed",
    "drops_upload_failed",
)

_CONFIG_FIELDS: tuple[str, ...] = (
    "clip_cadence_seconds",
    "video_capture_fps",
    "clip_window_ms",
    "app_build",
)


@router.post("/{session_id}/telemetry", response_model=ClipTelemetryResponse)
async def record_clip_telemetry(
    session_id: uuid.UUID,
    body: ClipTelemetryBeacon,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClipTelemetryResponse:
    """Record one iOS clip-pipeline telemetry beacon as an append-only
    audit event (#390).

    No state precondition (unlike `/export-audit`): drop + config-snapshot
    beacons fire DURING recording and the summary fires on stop, so the
    session can legitimately be in any state. Owner assertion still applies
    — a clinician can only beacon their own sessions. No bytes cross here;
    this is pure count/enum telemetry.
    """
    await get_owned_session_or_404(db, session_id, user)

    if body.kind == "drop":
        if body.reason is None:
            raise HTTPException(
                status_code=400, detail="kind='drop' requires a 'reason'."
            )
        if body.reason is ClipDropReason.SERVER_S3_PUT_FAILED:
            # Server-only reason — a device can't observe a server S3
            # failure, so reject it rather than let a client forge one.
            raise HTTPException(
                status_code=400,
                detail="reason 'server_s3_put_failed' is server-emitted only.",
            )
        fields: dict[str, object] = {"reason": body.reason.value, "origin": "ios"}
        if body.timestamp_ms is not None:
            fields["timestamp_ms"] = body.timestamp_ms
        await write_audit(session_id, AuditEventType.CLIP_DROPPED, **fields)

    elif body.kind == "summary":
        fields = {"origin": "ios"}
        for name in _SUMMARY_FIELDS:
            value = getattr(body, name)
            if value is not None:
                fields[name] = value
        await write_audit(session_id, AuditEventType.CLIP_PIPELINE_SUMMARY, **fields)

    else:  # config_snapshot
        fields = {"origin": "ios"}
        if body.visual_evidence_mode is not None:
            fields["visual_evidence_mode"] = body.visual_evidence_mode.value
        for name in _CONFIG_FIELDS:
            value = getattr(body, name)
            if value is not None:
                fields[name] = value
        await write_audit(session_id, AuditEventType.CLIP_CONFIG_SNAPSHOT, **fields)

    logger.info(
        "Clip telemetry: session=%s kind=%s",
        _session_log_prefix(session_id), body.kind,
    )
    return ClipTelemetryResponse(session_id=str(session_id), kind=body.kind)
