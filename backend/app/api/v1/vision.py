"""Vision API routes — Stage 2 frame processing.

POST /api/v1/vision/{session_id} — process frames for a session.

The route is also called internally from /notes/{id}/approve-stage1 via
`run_stage2_vision`, so iOS doesn't need to invoke it explicitly. The two
entry points share the same pipeline body.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, require_state, write_audit
from app.core.audit_events import AuditEventType
from app.core.database import get_db
from app.core.models import SessionModel, TranscriptModel
from app.core.types import Note, SessionState, Transcript
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.schema import VisualEvidenceMode
from app.modules.note_gen.service import (
    create_note_version,
    get_latest_note,
)
from app.modules.prompts import assemble_prompt
from app.modules.vision.clip_metrics import ClipTelemetry, record_clip_metrics
from app.modules.vision.reconcile import reconcile_captions
from app.modules.vision.service import (
    caption_visual_evidence,
    classify_conflicts,  # noqa: F401 — kept for backward-compat; new code uses reconcile_captions
    has_unresolved_conflicts,
    merge_visual_citations,
    resolve_evidence_mode,
    retrieve_clips_for_triggers,
    retrieve_frames_for_triggers,
)

logger = logging.getLogger("aurion.api.vision")

router = APIRouter(prefix="/vision", tags=["vision"])


class FrameCaptionResponse(BaseModel):
    frame_id: str
    session_id: str
    timestamp_ms: int
    audio_anchor_id: str
    provider_used: str
    visual_description: str
    confidence: str
    confidence_reason: str
    conflict_flag: bool
    conflict_detail: Optional[str] = None
    integration_status: str


class VisionProcessingResponse(BaseModel):
    session_id: str
    frames_processed: int
    frames_discarded: int
    enriches_count: int
    repeats_count: int
    conflicts_count: int
    captions: list[FrameCaptionResponse]


async def run_stage2_vision(
    session_id: uuid.UUID,
    db: AsyncSession,
) -> VisionProcessingResponse:
    """Run the Stage 2 vision pipeline for a session.

    Pipeline:
      1. Load the persisted transcript and the latest Stage 1 note
      2. Pull masked frames from S3 around trigger-flagged segments
      3. Caption frames via the active vision provider
      4. Classify each caption as ENRICHES / REPEATS / CONFLICTS
      5. Merge captions into a new Stage 2 note version
      6. Write audit events

    Returns a per-call summary. Called from both the public route and from
    /notes/{id}/approve-stage1 so the wiring is identical in both paths.
    """
    # 1. Transcript
    result = await db.execute(
        select(TranscriptModel).where(TranscriptModel.session_id == session_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # No transcript persisted — likely no audio was uploaded. Vision can't
        # run without trigger segments; return an empty result so the state
        # machine can move forward without hanging.
        await write_audit(session_id, AuditEventType.STAGE2_SKIPPED, reason="no_transcript")
        return VisionProcessingResponse(
            session_id=str(session_id),
            frames_processed=0, frames_discarded=0,
            enriches_count=0, repeats_count=0, conflicts_count=0,
            captions=[],
        )
    transcript = Transcript.model_validate_json(row.transcript_json)
    trigger_segments = [s for s in transcript.segments if s.is_visual_trigger]

    # 2. Latest note (must exist for merge)
    note: Note | None = await get_latest_note(str(session_id), db)
    if note is None:
        raise HTTPException(
            status_code=409,
            detail="No Stage 1 note found — cannot run vision enrichment.",
        )

    # If there are no triggers, skip the expensive S3+vision-provider work.
    if not trigger_segments:
        await write_audit(
            session_id,
            AuditEventType.STAGE2_COMPLETE,
            frames=0, conflicts=0,
            reason="no_visual_triggers",
        )
        return VisionProcessingResponse(
            session_id=str(session_id),
            frames_processed=0, frames_discarded=0,
            enriches_count=0, repeats_count=0, conflicts_count=0,
            captions=[],
        )

    # 3. Resolve evidence mode + retrieve frames and/or clips.
    #
    # P1-7 introduced per-session `visual_evidence_mode`; P1-FU-METRICS
    # threads the resolved mode here so the clip path participates in
    # Stage 2 dispatch + telemetry. Frame retrieval stays unchanged so
    # frames-only sessions (the pilot default) are byte-identical to
    # the pre-PR path.
    session_row = (
        await db.execute(
            select(SessionModel).where(SessionModel.id == session_id)
        )
    ).scalar_one_or_none()
    evidence_mode = (
        resolve_evidence_mode(session_row) if session_row is not None
        else VisualEvidenceMode.FRAMES_ONLY
    )

    frames = (
        await retrieve_frames_for_triggers(str(session_id), trigger_segments)
        if evidence_mode != VisualEvidenceMode.CLIPS_ONLY
        else []
    )
    clips = (
        await retrieve_clips_for_triggers(str(session_id), trigger_segments)
        if evidence_mode != VisualEvidenceMode.FRAMES_ONLY
        else []
    )
    evidence_items = [*frames, *clips]

    # 4. Captions — single dispatch site for the unified evidence list.
    # ``clip_telemetry`` is the per-clip telemetry sink; the captioning
    # loop appends one ``ClipTelemetry`` per clip that survives the
    # low-confidence + provider-fallback gauntlet.
    #
    # AI-PROMPTS-B: assemble the kind-specific (base + per-physician
    # overlay) system prompts once here. Both kinds share the same
    # underlying base today but they're separate registry entries —
    # the physician can customise them independently. We resolve both
    # so the dispatch loop never re-asks the DB.
    clinician_id = session_row.clinician_id if session_row is not None else None
    frame_system_prompt = (
        await assemble_prompt("vision_frame", clinician_id, db)
        if clinician_id is not None
        else None
    )
    clip_system_prompt = (
        await assemble_prompt("vision_clip", clinician_id, db)
        if clinician_id is not None
        else None
    )
    clip_telemetry: list[ClipTelemetry] = []
    captions_raw = await caption_visual_evidence(
        evidence=evidence_items,
        trigger_segments=trigger_segments,
        clip_telemetry_sink=clip_telemetry,
        frame_system_prompt=frame_system_prompt,
        clip_system_prompt=clip_system_prompt,
    )

    # Drop low-confidence captions before conflict classification.
    captions_filtered = [c for c in captions_raw if c.confidence != "low"]
    discarded = len(captions_raw) - len(captions_filtered)

    # 5. Conflict reconciliation — real LLM comparison of the Stage 1
    #    note's claims against the captions sharing each audio anchor.
    #    Replaces the previous "trust the vision provider's
    #    integration_status" shortcut. See vision/reconcile.py.
    #
    # AI-PROMPTS-B: assemble the conflict_reconciliation overlay for
    # the calling clinician. Same DB session, same clinician_id —
    # cheap lookup, single SELECT.
    reconcile_system_prompt = (
        await assemble_prompt("conflict_reconciliation", clinician_id, db)
        if clinician_id is not None
        else None
    )
    captions = await reconcile_captions(
        captions_filtered, note, system_prompt=reconcile_system_prompt
    )

    # 6. Merge into a new Stage 2 note version
    enriched = merge_visual_citations(note, captions)
    enriched.session_id = str(session_id)
    enriched.stage = 2
    await create_note_version(str(session_id), enriched, db)

    enriches = sum(1 for c in captions if c.integration_status == "ENRICHES")
    repeats = sum(1 for c in captions if c.integration_status == "REPEATS")
    conflicts = sum(1 for c in captions if c.integration_status == "CONFLICTS")

    await write_audit(
        session_id,
        AuditEventType.STAGE2_COMPLETE,
        frames_processed=len(frames),
        frames_discarded=discarded,
        enriches=enriches,
        repeats=repeats,
        conflicts=conflicts,
        unresolved_conflicts=has_unresolved_conflicts(captions),
    )

    # P1-FU-METRICS: persist per-session clip cost/latency/byte
    # aggregates to pilot_metrics. No-op when no clips were processed
    # (frame-only sessions). Wrapped in record_clip_metrics' own
    # try/except so a passive-metrics failure cannot break Stage 2.
    await record_clip_metrics(db, str(session_id), clip_telemetry)

    logger.info(
        "Stage 2 complete: session=%s frames=%d clips=%d enriches=%d conflicts=%d",
        session_id, len(frames), len(clips), enriches, conflicts,
    )

    return VisionProcessingResponse(
        session_id=str(session_id),
        frames_processed=len(frames),
        frames_discarded=discarded,
        enriches_count=enriches,
        repeats_count=repeats,
        conflicts_count=conflicts,
        captions=[
            FrameCaptionResponse(
                frame_id=c.frame_id,
                session_id=c.session_id,
                timestamp_ms=c.timestamp_ms,
                audio_anchor_id=c.audio_anchor_id,
                provider_used=c.provider_used,
                visual_description=c.visual_description,
                confidence=c.confidence,
                confidence_reason=c.confidence_reason or "",
                conflict_flag=c.conflict_flag,
                conflict_detail=c.conflict_detail,
                integration_status=c.integration_status,
            )
            for c in captions
        ],
    )


@router.post("/{session_id}", response_model=VisionProcessingResponse)
async def process_vision_frames(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Process masked frames for a session through the vision pipeline."""
    session = await get_owned_session_or_404(db, session_id, user)
    require_state(session, SessionState.PROCESSING_STAGE2)
    return await run_stage2_vision(session_id, db)
