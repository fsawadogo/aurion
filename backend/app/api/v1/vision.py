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
from app.core.types import Note, SessionState, Template, Transcript
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.appconfig_client import get_config
from app.modules.config.schema import VisualEvidenceMode
from app.modules.note_gen.service import (
    create_note_version,
    get_latest_note,
    resolve_session_template,
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

    # 3. Resolve evidence mode (needed before the no-trigger short-circuit).
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

    # No-trigger short-circuit (#324 — relaxed). Frames are extracted ONLY
    # at trigger timestamps, so a FRAMES_ONLY session with zero spoken
    # triggers has nothing to retrieve and fast-skips (existing behavior).
    # But clips are extracted on a cadence floor independent of spoken
    # triggers, so CLIPS_ONLY / HYBRID must PROCEED with zero triggers —
    # a silent physical exam still produces cadence clips to caption.
    if not trigger_segments and evidence_mode == VisualEvidenceMode.FRAMES_ONLY:
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

    # Retrieve frames and/or clips per the resolved mode.
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
    # AI-PROMPTS-B: select the kind-specific system prompt once here
    # — the calling physician's saved user prompt when set, the
    # registry default otherwise (REPLACEMENT). Both kinds share the
    # same underlying default today but they're separate registry
    # entries — the physician can customise them independently. We
    # resolve both so the dispatch loop never re-asks the DB.
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
    # TE-3: the template + note let captioning aim at the section each frame
    # will feed, instead of describing generically. Resolved from the session's
    # stored PIN so Stage 2 uses the SAME template Stage 1 did.
    #
    # Resolved ONCE, here, for two reasons:
    #
    #   * FAIL SAFE. Everything else in TE-3 degrades to None; this is the only
    #     step that can raise. `resolve_session_template` reaches into
    #     custom_templates (a table Stage 2 never touched before TE-3) and
    #     `get_template` raises ValueError when a key resolves to nothing. An
    #     escape here fails the whole Stage 2 job and fires a CRITICAL alert —
    #     turning "your template guidance was unavailable" into "your note
    #     didn't generate". A bad template must never block a physician.
    #   * ONE CONFIG SNAPSHOT PER RUN. get_config() is a 30s poller, and Stage
    #     2's SLA is under 5 minutes, so a mid-run flip is reachable. Reading
    #     the flag per frame would let one note contain both aimed and unaimed
    #     captions. Deciding once keeps a run internally consistent.
    template_for_capture: Template | None = None
    if session_row is not None and get_config().feature_flags.template_engine_enabled:
        try:
            template_for_capture = await resolve_session_template(session_row, db)
        except Exception:
            # PHI-safe: session id only, no template content.
            logger.warning(
                "Template resolution failed for session=%s; captioning with "
                "the base prompt", session_id, exc_info=True,
            )
            template_for_capture = None

    # Grounded visual findings — resolve ONCE per run (same one-snapshot
    # discipline as template_engine above): the flag lets the vision layer
    # state cited clinical findings instead of literal descriptions. Reading
    # it per frame could mix grounded and descriptive captions in one note.
    grounded_visual = get_config().feature_flags.grounded_visual_findings_enabled

    clip_telemetry: list[ClipTelemetry] = []
    captions_raw = await caption_visual_evidence(
        evidence=evidence_items,
        trigger_segments=trigger_segments,
        clip_telemetry_sink=clip_telemetry,
        frame_system_prompt=frame_system_prompt,
        clip_system_prompt=clip_system_prompt,
        # #324: anchor clips against the FULL transcript (incidental speech
        # near a cadence clip), not just spoken triggers.
        anchor_segments=transcript.segments,
        template=template_for_capture,
        note=note,
        grounded=grounded_visual,
    )

    # Drop low-confidence captions before conflict classification.
    captions_filtered = [c for c in captions_raw if c.confidence != "low"]
    discarded = len(captions_raw) - len(captions_filtered)

    # 5. Conflict reconciliation — real LLM comparison of the Stage 1
    #    note's claims against the captions sharing each audio anchor.
    #    Replaces the previous "trust the vision provider's
    #    integration_status" shortcut. See vision/reconcile.py.
    #
    # AI-PROMPTS-B: select the conflict_reconciliation user prompt
    # (replacement) or registry default for the calling clinician.
    # Same DB session, same clinician_id — cheap lookup, single SELECT.
    reconcile_system_prompt = (
        await assemble_prompt("conflict_reconciliation", clinician_id, db)
        if clinician_id is not None
        else None
    )
    captions = await reconcile_captions(
        captions_filtered, note, system_prompt=reconcile_system_prompt
    )

    # 6. Merge into a new Stage 2 note version. ``stats_trigger`` flows
    # into the SESSION_STATS_RECOMPUTED audit row so dashboards can
    # tell "Stage 2 enrichment moved the needle" apart from
    # "physician edit moved the needle".
    # TE-4: the merge must be given the SAME routing inputs capture was, or a
    # frame is aimed at one section's guidance and filed under another. That
    # means the template AND the anchor text its trigger keywords match on.
    enriched = merge_visual_citations(
        note,
        captions,
        template_for_capture,
        {s.id: s.text for s in transcript.segments},
    )
    enriched.session_id = str(session_id)
    enriched.stage = 2
    await create_note_version(
        str(session_id), enriched, db, stats_trigger="vision_merge"
    )

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
