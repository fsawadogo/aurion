"""Notes API routes -- Stage 1 draft, approval, full note retrieval.

No business logic here -- routes call module service functions only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import get_owned_session_or_404, write_audit
from app.core.audit_events import AuditEventType
from app.core.database import async_session_factory, get_db
from app.core.models import TranscriptModel
from app.core.types import SessionState, Transcript
from app.modules.alerts.service import AlertSeverity, try_publish_alert
from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.note_gen.service import (
    approve_note,
    edit_note,
    get_latest_note,
    get_note_by_stage,
    is_note_approved,
    resolve_conflict,
)
from app.modules.session.service import (
    InvalidTransitionError,
    transition_session,
)
from app.modules.vision.jobs import (
    create_job,
    get_latest_job,
    mark_completed,
    mark_failed,
    mark_running,
)

logger = logging.getLogger("aurion.api.notes")

router = APIRouter(prefix="/notes", tags=["notes"])


# ── Response Schemas ─────────────────────────────────────────────────────

class NoteClaimResponse(BaseModel):
    id: str
    text: str
    source_type: str
    source_id: str
    source_quote: str = ""
    physician_edited: bool = False
    original_text: Optional[str] = None


class NoteSectionResponse(BaseModel):
    id: str
    title: str = ""
    status: str = "not_captured"
    claims: list[NoteClaimResponse] = []


class NoteResponse(BaseModel):
    session_id: str
    stage: int
    version: int
    provider_used: str
    specialty: str
    completeness_score: float
    sections: list[NoteSectionResponse]


# ── Detail response (citation expansion + conflict + export state) ───────

class CitationExpansion(BaseModel):
    """Per-claim source detail for the review UI. The shape depends on
    `source_type`; only the fields relevant to that source are populated."""

    source_type: str
    source_id: str
    # transcript anchor
    transcript_text: Optional[str] = None
    transcript_speaker: Optional[str] = None
    transcript_start_ms: Optional[int] = None
    transcript_end_ms: Optional[int] = None
    # visual / screen anchor — both reference a frame_id
    frame_timestamp_ms: Optional[int] = None
    frame_s3_key: Optional[str] = None
    # physician edit
    original_text: Optional[str] = None


class ConflictState(BaseModel):
    """Aggregate of unresolved CONFLICTS across the note. Surfaced so the
    web review UI can block approval and jump to the offending sections.
    """

    has_unresolved: bool
    unresolved_count: int
    unresolved_section_ids: list[str] = []
    unresolved_claim_ids: list[str] = []


class ExportMetadata(BaseModel):
    latest_version: int
    is_approved: bool
    can_export: bool
    session_state: str
    # Patient identifier — decrypted server-side, only populated for
    # the row's owner (the NoteDetail endpoint already routes through
    # get_owned_session_or_404, so any non-owner caller never reaches
    # this builder). Null when not set.
    external_reference_id: Optional[str] = None


class NoteDetailResponse(BaseModel):
    """Full note for the web review UI. Adds per-claim citation expansion,
    a conflict-resolution summary, and export readiness state on top of
    the wire `NoteResponse`."""

    note: NoteResponse
    citations: dict[str, CitationExpansion]
    conflict_state: ConflictState
    export_metadata: ExportMetadata


class NoteApprovalResponse(BaseModel):
    session_id: str
    stage: int
    version: int
    approved: bool
    message: str


class Stage2StatusResponse(BaseModel):
    """Async Stage 2 job state surfaced to the client.

    `status` is `pending | running | completed | failed` (matching the
    `vision.jobs` literals). `no_job` means Stage 1 hasn't been approved
    yet — clients should treat that as "Stage 2 hasn't started" rather
    than as an error. `new_note_version` is populated only on completion;
    iOS uses it as the refetch trigger.
    """

    session_id: str
    job_id: Optional[str] = None
    status: Literal["no_job", "pending", "running", "completed", "failed"]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    new_note_version: Optional[int] = None
    frames_processed: int = 0
    error_message: Optional[str] = None


class NoteEditRequest(BaseModel):
    """Request body for physician note edits.

    edits: dict mapping section_id to new claim text.
    Example: {"physical_exam": "Updated claim text...", "assessment": "..."}
    """
    edits: dict[str, str]


class ConflictResolutionRequest(BaseModel):
    """Resolve a single Stage 2 visual conflict.

    - "accept_visual": keep the visual claim. The audio narration was wrong.
    - "reject_visual": discard the conflict. The audio was right.
    - "edit": replace the claim text with `resolution_text`.
    """

    action: Literal["accept_visual", "reject_visual", "edit"]
    resolution_text: Optional[str] = None


# Sessions in these states allow note edits or conflict resolution. Stage 1
# review (AWAITING_REVIEW) or mid-Stage-2 (PROCESSING_STAGE2) are both fair
# game; later states are sealed.
_NOTE_MUTABLE_STATES: set[SessionState] = {
    SessionState.AWAITING_REVIEW,
    SessionState.PROCESSING_STAGE2,
}


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/{session_id}/stage1", response_model=NoteResponse)
async def get_stage1_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the Stage 1 draft note for a session.

    The session must be in AWAITING_REVIEW or later state for the
    Stage 1 note to be available.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    valid_states = {
        SessionState.AWAITING_REVIEW,
        SessionState.PROCESSING_STAGE2,
        SessionState.REVIEW_COMPLETE,
        SessionState.EXPORTED,
    }
    if session.state not in valid_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Stage 1 note not yet available. "
                f"Session is in {session.state.value}, must be in AWAITING_REVIEW or later."
            ),
        )

    note = await get_note_by_stage(str(session_id), stage=1, db=db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stage 1 note not found for this session.",
        )

    return _to_note_response(note)


@router.post("/{session_id}/approve-stage1", response_model=NoteApprovalResponse)
async def approve_stage1_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve the Stage 1 draft and trigger Stage 2 processing.

    Transitions the session from AWAITING_REVIEW to PROCESSING_STAGE2.
    Writes audit log events for the approval and state transition.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    if session.state != SessionState.AWAITING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot approve Stage 1: session is in {session.state.value}, "
                f"must be in AWAITING_REVIEW."
            ),
        )

    note = await get_note_by_stage(str(session_id), stage=1, db=db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Stage 1 note found to approve.",
        )

    try:
        approved_note = await approve_note(str(session_id), db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    try:
        await transition_session(db, session, SessionState.PROCESSING_STAGE2)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    await write_audit(
        session_id,
        AuditEventType.STAGE1_APPROVED,
        version=approved_note.version,
        provider_used=approved_note.provider_used,
        completeness_score=approved_note.completeness_score,
    )

    # Stage 2 used to run inline here, blocking the response for the full
    # SLA window. Now it's dispatched as a background task with its own DB
    # session; the row in `stage2_jobs` lets iOS poll status and lets the
    # dashboard show progress without holding open the original request.
    #
    # The `create_task` is intentionally fire-and-forget: if the FastAPI
    # process shuts down mid-job the task is dropped, which is acceptable
    # because Stage 1 is already approved and the job row stays at
    # `running` — an operator (or a recovery sweep) can re-enqueue if
    # needed. Stage 2 is best-effort; iOS can fall back to the Stage 1
    # note in the meantime.
    job = await create_job(session_id, db)
    await write_audit(session_id, AuditEventType.STAGE2_STARTED, job_id=str(job.id))
    asyncio.create_task(_run_stage2_in_background(session_id, job.id))

    return NoteApprovalResponse(
        session_id=str(session_id),
        stage=1,
        version=approved_note.version,
        approved=True,
        message="Stage 1 approved. Stage 2 visual enrichment processing started.",
    )


async def _run_stage2_in_background(session_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Run vision enrichment in a detached task, updating the job row as it
    progresses. Owns its own DB session because the request that scheduled
    it has already returned and committed.

    Failures are recorded on the job row and emit a `stage2_failed` audit
    event — they do NOT bubble: Stage 1 is approved and iOS can fall back
    to the Stage 1 note while compliance triages the failure.
    """
    from app.api.v1.vision import run_stage2_vision  # avoid circular import

    async with async_session_factory() as db:
        try:
            await mark_running(job_id, db)
            result = await run_stage2_vision(session_id, db)
            latest = await get_latest_note(str(session_id), db)
            new_version = latest.version if latest is not None else 0
            await mark_completed(
                job_id,
                new_note_version=new_version,
                frames_processed=result.frames_processed,
                db=db,
            )
        except Exception as exc:  # noqa: BLE001 — we deliberately catch all
            logger.exception("Stage 2 background job failed: session=%s job=%s", session_id, job_id)
            try:
                await mark_failed(job_id, str(exc), db)
            except Exception:
                # Last-ditch logging; nothing else useful we can do here.
                logger.exception("Failed to mark Stage 2 job failed: %s", job_id)
            await write_audit(
                session_id,
                AuditEventType.STAGE2_FAILED,
                job_id=str(job_id),
                reason=str(exc)[:200],
            )
            # Issue #76 — Stage 2 background-job failure is CRITICAL.
            await try_publish_alert(
                alert_type=AuditEventType.STAGE2_FAILED.value,
                severity=AlertSeverity.CRITICAL,
                source="stage2_job",
                message="Stage 2 background job failed",
                metadata={
                    "session_id": str(session_id),
                    "job_id": str(job_id),
                    "reason": str(exc)[:200],
                },
            )


@router.get("/{session_id}/full", response_model=NoteResponse)
async def get_full_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full note (latest version) for a session.

    Returns the most recent note version, which may include Stage 2
    visual enrichments if processing is complete.
    """
    await get_owned_session_or_404(db, session_id, user)

    note = await get_latest_note(str(session_id), db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No note found for this session.",
        )

    return _to_note_response(note)


@router.post("/{session_id}/approve", response_model=NoteApprovalResponse)
async def approve_final_note(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve the final note after Stage 2 visual enrichment.

    Transitions the session to REVIEW_COMPLETE. Writes audit log event.

    CONFLICTS must be resolved before approval -- no note with unresolved
    CONFLICTS can be approved.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    allowed_states = {SessionState.PROCESSING_STAGE2, SessionState.REVIEW_COMPLETE}
    if session.state not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot approve final note: session is in {session.state.value}. "
                f"Must be in PROCESSING_STAGE2 or REVIEW_COMPLETE."
            ),
        )

    note = await get_latest_note(str(session_id), db)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No note found to approve.",
        )

    _check_unresolved_conflicts(note)

    already_approved = await is_note_approved(str(session_id), db)
    if already_approved and session.state == SessionState.REVIEW_COMPLETE:
        return NoteApprovalResponse(
            session_id=str(session_id),
            stage=note.stage,
            version=note.version,
            approved=True,
            message="Note was already approved.",
        )

    try:
        approved_note = await approve_note(str(session_id), db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    if session.state == SessionState.PROCESSING_STAGE2:
        try:
            await transition_session(db, session, SessionState.REVIEW_COMPLETE)
        except InvalidTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )

    await write_audit(
        session_id,
        AuditEventType.FULL_NOTE_DELIVERED,
        version=approved_note.version,
        provider_used=approved_note.provider_used,
        completeness_score=approved_note.completeness_score,
    )

    return NoteApprovalResponse(
        session_id=str(session_id),
        stage=approved_note.stage,
        version=approved_note.version,
        approved=True,
        message="Final note approved. Ready for export.",
    )


@router.get("/{session_id}/detail", response_model=NoteDetailResponse)
async def get_note_detail(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Note detail optimized for the web review UI.

    Returns the latest note version plus:
      - `citations`: per-claim expansion (transcript text, frame metadata,
        physician-edit original text) keyed by `claim.id`.
      - `conflict_state`: aggregate of unresolved CONFLICTS so the UI
        can block approval at the page level, not just at submit.
      - `export_metadata`: approval + session state so the export button
        knows whether to be active.
    """
    # Session has to come back first — 404 short-circuit. The remaining
    # three reads (note, transcript, approved-flag) are independent, so
    # fan them out with gather to keep the detail page snappy on web.
    session = await get_owned_session_or_404(db, session_id, user)

    note, transcript, approved = await asyncio.gather(
        get_latest_note(str(session_id), db),
        _load_transcript(db, session_id),
        is_note_approved(str(session_id), db),
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No note found for this session.",
        )

    citations = _build_citations(note, transcript, session_id=str(session_id))
    conflict_state = _summarize_conflicts(note)
    external_id: Optional[str] = None
    if session.external_reference_id_encrypted:
        try:
            from app.core.kms_encryption import decrypt_str

            external_id = decrypt_str(session.external_reference_id_encrypted)
        except Exception:
            # Same swallow-and-omit pattern as sessions._to_response —
            # CMK rotation failures never 500 the review page.
            external_id = None
    export_metadata = ExportMetadata(
        latest_version=note.version,
        is_approved=approved,
        can_export=session.state in {SessionState.REVIEW_COMPLETE, SessionState.EXPORTED},
        session_state=session.state.value,
        external_reference_id=external_id,
    )

    return NoteDetailResponse(
        note=_to_note_response(note),
        citations=citations,
        conflict_state=conflict_state,
        export_metadata=export_metadata,
    )


@router.get("/{session_id}/stage2-status", response_model=Stage2StatusResponse)
async def get_stage2_status(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll Stage 2 job status. iOS hits this from the dashboard to know
    whether the session is still processing, ready for final review, or
    blocked on a vision failure.

    Returns `status="no_job"` (with a 200, not 404) when Stage 1 hasn't
    been approved yet — clients should treat that as "Stage 2 hasn't
    started" rather than an error.
    """
    await get_owned_session_or_404(db, session_id, user)

    job = await get_latest_job(session_id, db)
    if job is None:
        return Stage2StatusResponse(session_id=str(session_id), status="no_job")
    return Stage2StatusResponse(
        session_id=str(session_id),
        job_id=str(job.id),
        status=job.status,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        new_note_version=job.new_note_version,
        frames_processed=job.frames_processed,
        error_message=job.error_message,
    )


@router.patch(
    "/{session_id}/conflicts/{claim_id}/resolve",
    response_model=NoteResponse,
)
async def resolve_conflict_endpoint(
    session_id: uuid.UUID,
    claim_id: str,
    body: ConflictResolutionRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a single Stage 2 visual conflict.

    Writes a new immutable note version with the conflict either accepted,
    rejected, or edited. The audit log captures the action so compliance
    can review every resolution decision.

    Session must be in AWAITING_REVIEW or PROCESSING_STAGE2 — conflicts
    only exist after Stage 2, and resolution must precede final approval.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    if session.state not in _NOTE_MUTABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot resolve conflict: session is in {session.state.value}. "
                f"Must be in AWAITING_REVIEW or PROCESSING_STAGE2."
            ),
        )

    try:
        updated = await resolve_conflict(
            session_id=str(session_id),
            claim_id=claim_id,
            action=body.action,
            resolution_text=body.resolution_text,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await write_audit(
        session_id,
        AuditEventType.CONFLICT_RESOLVED,
        claim_id=claim_id,
        action=body.action,
        new_version=updated.version,
    )

    return _to_note_response(updated)


@router.patch("/{session_id}/edit", response_model=NoteResponse)
async def edit_note_endpoint(
    session_id: uuid.UUID,
    body: NoteEditRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply physician edits to the latest note version.

    Creates a new immutable version -- the original is preserved.
    Session must be in AWAITING_REVIEW or REVIEW_COMPLETE state.
    """
    session = await get_owned_session_or_404(db, session_id, user)

    allowed_states = {SessionState.AWAITING_REVIEW, SessionState.REVIEW_COMPLETE}
    if session.state not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot edit note: session is in {session.state.value}. "
                f"Must be in AWAITING_REVIEW or REVIEW_COMPLETE."
            ),
        )

    if not body.edits:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No edits provided.",
        )

    try:
        updated_note = await edit_note(str(session_id), body.edits, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    await write_audit(
        session_id,
        AuditEventType.NOTE_VERSION_CREATED,
        version=updated_note.version,
        sections_edited=list(body.edits.keys()),
    )

    return _to_note_response(updated_note)


# ── Helpers ──────────────────────────────────────────────────────────────

def _check_unresolved_conflicts(note) -> None:
    """Raise 409 if the note has any unresolved CONFLICTS from vision."""
    state = _summarize_conflicts(note)
    if state.has_unresolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Unresolved conflict in section '{state.unresolved_section_ids[0]}'. "
                "All conflicts must be resolved before approval."
            ),
        )


def _is_unresolved_conflict(claim) -> bool:
    """A vision conflict claim that hasn't been resolved by an edit. Once
    a physician edits a conflict claim it flips to `physician_edited=True`
    and is considered resolved."""
    return (
        claim.source_type == "visual"
        and claim.id.startswith("conflict_")
        and not claim.physician_edited
    )


def _summarize_conflicts(note) -> ConflictState:
    section_ids: list[str] = []
    claim_ids: list[str] = []
    for section in note.sections:
        for claim in section.claims:
            if _is_unresolved_conflict(claim):
                if section.id not in section_ids:
                    section_ids.append(section.id)
                claim_ids.append(claim.id)
    return ConflictState(
        has_unresolved=bool(claim_ids),
        unresolved_count=len(claim_ids),
        unresolved_section_ids=section_ids,
        unresolved_claim_ids=claim_ids,
    )


async def _load_transcript(db: AsyncSession, session_id: uuid.UUID) -> Optional[Transcript]:
    """Best-effort transcript fetch for citation expansion. Returns None if
    the transcript hasn't been persisted yet (e.g. note exists but Stage 1
    raced ahead of transcript storage in tests)."""
    result = await db.execute(
        select(TranscriptModel).where(TranscriptModel.session_id == session_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    try:
        return Transcript.model_validate(json.loads(row.transcript_json))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Transcript JSON unparseable for session=%s: %s", session_id, exc)
        return None


def _build_citations(
    note,
    transcript: Optional[Transcript],
    *,
    session_id: str,
) -> dict[str, CitationExpansion]:
    """Build per-claim source expansion. The web review UI shows this
    under each claim so the clinician can verify the anchor without
    leaving the page."""
    segment_index: dict[str, object] = {}
    if transcript is not None:
        segment_index = {seg.id: seg for seg in transcript.segments}

    citations: dict[str, CitationExpansion] = {}
    for section in note.sections:
        for claim in section.claims:
            citations[claim.id] = _expand_claim(claim, segment_index, session_id=session_id)
    return citations


def _expand_claim(
    claim,
    segment_index: dict,
    *,
    session_id: str,
) -> CitationExpansion:
    if claim.source_type == "transcript":
        seg = segment_index.get(claim.source_id)
        if seg is not None:
            return CitationExpansion(
                source_type="transcript",
                source_id=claim.source_id,
                transcript_text=seg.text,
                transcript_speaker=seg.speaker,
                transcript_start_ms=seg.start_ms,
                transcript_end_ms=seg.end_ms,
                original_text=claim.original_text,
            )
        # Transcript not yet persisted — fall back to the quote captured at claim time.
        return CitationExpansion(
            source_type="transcript",
            source_id=claim.source_id,
            transcript_text=claim.source_quote or None,
            original_text=claim.original_text,
        )

    if claim.source_type in ("visual", "screen"):
        # The frame id encodes the timestamp (`frame_NNNNN` / `screen_NNNNN`).
        # S3 key reconstruction matches the upload-side layout.
        prefix = "frames" if claim.source_type == "visual" else "screen_frames"
        timestamp = _parse_frame_timestamp(claim.source_id)
        s3_key = (
            f"{prefix}/{session_id}/{timestamp}.jpg" if timestamp is not None else None
        )
        return CitationExpansion(
            source_type=claim.source_type,
            source_id=claim.source_id,
            frame_timestamp_ms=timestamp,
            frame_s3_key=s3_key,
            original_text=claim.original_text,
        )

    # physician_edit
    return CitationExpansion(
        source_type=claim.source_type,
        source_id=claim.source_id,
        original_text=claim.original_text,
    )


def _parse_frame_timestamp(source_id: str) -> Optional[int]:
    """Frame ids are `frame_NNNNN` / `screen_NNNNN` where N is timestamp_ms.
    Defensive: return None if the suffix isn't an int."""
    parts = source_id.rsplit("_", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _to_note_response(note) -> NoteResponse:
    """Convert a Note domain object to a NoteResponse."""
    return NoteResponse(
        session_id=note.session_id,
        stage=note.stage,
        version=note.version,
        provider_used=note.provider_used,
        specialty=note.specialty,
        completeness_score=note.completeness_score,
        sections=[
            NoteSectionResponse(
                id=s.id,
                title=s.title,
                status=s.status,
                claims=[
                    NoteClaimResponse(
                        id=c.id,
                        text=c.text,
                        source_type=c.source_type,
                        source_id=c.source_id,
                        source_quote=c.source_quote,
                        physician_edited=c.physician_edited,
                        original_text=c.original_text,
                    )
                    for c in s.claims
                ],
            )
            for s in note.sections
        ],
    )
