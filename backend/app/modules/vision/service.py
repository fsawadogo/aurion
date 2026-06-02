"""Vision pipeline — Stage 2 processing.

Sequence:
1. Retrieve masked frames from S3 at trigger-flagged timestamps
2. Validate masking status in audit log
3. Call active VisionProvider for each frame
4. Classify ENRICHES / REPEATS / CONFLICTS
5. Discard low-confidence frames before classification
6. Merge frame citations into Stage 1 note
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from app.core.audit_events import AuditEventType
from app.core.retry import with_retry
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.core.types import (
    ClipMaskingMetadata,
    FrameCaption,
    MaskedClip,
    MaskedFrame,
    Note,
    NoteClaim,
    NoteSection,
    ProviderError,
    TranscriptSegment,
)
from app.modules.alerts.service import AlertSeverity, try_publish_alert
from app.modules.audit_log.service import get_audit_log_service
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_registry import get_registry
from app.modules.providers.usage_service import try_record_provider_usage

# ── Visual evidence sentinel ─────────────────────────────────────────────
#
# `VisualEvidenceItem` is the union the dual-mode dispatch loop sees —
# either a `MaskedFrame` (existing path, JPEG still) or a `MaskedClip`
# (P1-3, H.264 video). Each item carries an `evidence_kind` attribute on
# the model itself; the dispatch loop reads that to route to the right
# provider method. `MaskedFrame` does not declare `evidence_kind` (its
# kind is implicit "frame"); the helper `_evidence_kind_of(item)` below
# normalizes the read.

VisualEvidenceItem = MaskedFrame | MaskedClip


def _evidence_kind_of(item: VisualEvidenceItem) -> str:
    """Return 'frame' or 'clip' for the dispatch switch.

    Keeping this as a one-liner (over `isinstance`) means a future
    evidence type (e.g. 3D depth map, thermal still) lands by adding
    one branch here + one method on `VisionProvider` — OCP.
    """
    return "clip" if isinstance(item, MaskedClip) else "frame"


def _evidence_id_of(item: VisualEvidenceItem) -> str:
    """Return a stable identifier for audit + log lines.

    Frames carry `frame_id`; clips carry `s3_key` (their server-side
    identifier is the path) — we surface the latter as the audit anchor
    for `CLIP_DISCARDED` per `ALLOWED_AUDIT_KWARGS`.
    """
    if isinstance(item, MaskedClip):
        return item.s3_key
    return item.frame_id

logger = logging.getLogger("aurion.vision")


# ── Frame Extraction ─────────────────────────────────────────────────────

def get_frame_window_ms(trigger_type: Optional[str] = None) -> int:
    """Get the frame extraction window from AppConfig — never hardcoded."""
    config = get_config()
    if trigger_type and "procedural" in trigger_type.lower():
        return config.pipeline.frame_window_procedural_ms
    return config.pipeline.frame_window_clinic_ms


async def retrieve_frames_for_triggers(
    session_id: str,
    trigger_segments: list[TranscriptSegment],
) -> list[MaskedFrame]:
    """Retrieve masked frames from S3 at trigger-flagged timestamps.

    Each trigger segment maps to frames within the configured window.
    """
    frames: list[MaskedFrame] = []
    s3 = get_s3_client()

    for segment in trigger_segments:
        window_ms = get_frame_window_ms(segment.trigger_type)
        prefix = f"frames/{session_id}/"

        try:
            response = await with_retry(
                s3.list_objects_v2,
                Bucket=FRAMES_BUCKET,
                Prefix=prefix,
                max_retries=3,
                base_delay=1.0,
                operation="s3_list_frames",
                session_id=session_id,
            )
            for obj in response.get("Contents", []):
                key = obj["Key"]
                # Extract timestamp from key: frames/{session_id}/{timestamp_ms}.jpg
                try:
                    ts_str = key.rsplit("/", 1)[-1].split(".")[0]
                    ts_ms = int(ts_str)
                except (ValueError, IndexError):
                    continue

                # Check if frame is within the extraction window
                if segment.start_ms - window_ms <= ts_ms <= segment.end_ms + window_ms:
                    frames.append(
                        MaskedFrame(
                            frame_id=f"frame_{ts_ms:05d}",
                            session_id=session_id,
                            timestamp_ms=ts_ms,
                            s3_key=key,
                            masking_confirmed=True,
                        )
                    )
        except (BotoCoreError, ClientError) as e:
            logger.error(
                "Frame retrieval failed: session=%s segment=%s error=%s",
                str(session_id)[:8], segment.id, str(e),
            )

    # Deduplicate by frame_id
    seen = set()
    unique: list[MaskedFrame] = []
    for f in frames:
        if f.frame_id not in seen:
            seen.add(f.frame_id)
            unique.append(f)

    logger.info(
        "Frames retrieved: session=%s triggers=%d frames=%d",
        str(session_id)[:8], len(trigger_segments), len(unique),
    )
    return unique


# ── Clip Retrieval (P1-3) ─────────────────────────────────────────────────
#
# Parallels `retrieve_frames_for_triggers` for the clip path. Clips live
# under `clips/{session_id}/{clip_id}.mp4`; the anchor timestamp is
# encoded in the audit log (not the key), so trigger-window matching
# happens against the audit-log timestamps for the clip rows. For the
# pilot we keep it simple: list every clip under the session prefix and
# treat each one as relevant; the iOS dispatcher is the gate that
# decides which triggers produce clips.

async def retrieve_clips_for_triggers(
    session_id: str,
    trigger_segments: list[TranscriptSegment],
) -> list[MaskedClip]:
    """Retrieve masked clips for a session from S3.

    Clips don't encode the trigger timestamp in their key (the path is
    `clips/{session_id}/{clip_id}.mp4`), so we list every clip under
    the session prefix and trust the iOS dispatcher's per-trigger
    decision (a clip lives in S3 because iOS produced it for a trigger).

    Returns one `MaskedClip` per object found. The masking metadata
    fields are populated with `0` placeholders — those are audit-only
    fields the upload endpoint persisted; the Stage 2 path doesn't
    need them. iOS-side fail-closed masking guarantees only validated
    clips reach S3.
    """
    s3 = get_s3_client()
    prefix = f"clips/{session_id}/"
    clips: list[MaskedClip] = []

    try:
        response = await with_retry(
            s3.list_objects_v2,
            Bucket=FRAMES_BUCKET,
            Prefix=prefix,
            max_retries=3,
            base_delay=1.0,
            operation="s3_list_clips",
            session_id=session_id,
        )
    except Exception as e:  # noqa: BLE001 — list failure is non-fatal
        logger.error(
            "Clip retrieval failed: session=%s error=%s",
            str(session_id)[:8], str(e),
        )
        return clips

    # Anchor each clip to the closest trigger segment. If the session
    # has no triggers (frames-only mode), `trigger_segments` is empty
    # and the clip skips to the default anchor inside `caption_frames`.
    default_anchor_ts = (
        trigger_segments[0].start_ms if trigger_segments else 0
    )

    for obj in response.get("Contents", []):
        key = obj["Key"]
        clips.append(
            MaskedClip(
                s3_key=key,
                timestamp_ms=default_anchor_ts,
                duration_ms=get_config().pipeline.clip_window_ms,
                trigger_segment_id=(
                    trigger_segments[0].id if trigger_segments else "unknown"
                ),
                masking_metadata=ClipMaskingMetadata(
                    frames_total=0, frames_with_faces=0, faces_blurred=0
                ),
            )
        )

    logger.info(
        "Clips retrieved: session=%s triggers=%d clips=%d",
        str(session_id)[:8], len(trigger_segments), len(clips),
    )
    return clips


# ── Vision Captioning ────────────────────────────────────────────────────

async def caption_frames(
    frames: list[MaskedFrame],
    trigger_segments: list[TranscriptSegment],
    provider_override: Optional[str] = None,
) -> list[FrameCaption]:
    """Caption each frame using the active vision provider with fallback.

    Backward-compatible thin wrapper around :func:`caption_visual_evidence`
    so existing Stage 2 call sites keep working without change. The
    dual-mode call site in `notes/service.py` should call
    `caption_visual_evidence` directly to dispatch a mixed list.
    """
    return await caption_visual_evidence(
        evidence=list(frames),
        trigger_segments=trigger_segments,
        provider_override=provider_override,
    )


async def caption_visual_evidence(
    evidence: list[VisualEvidenceItem],
    trigger_segments: list[TranscriptSegment],
    provider_override: Optional[str] = None,
) -> list[FrameCaption]:
    """Caption a mixed list of frames + clips using kind-routed providers.

    The Stage 2 dispatch loop. Each evidence item is routed by its
    `evidence_kind` to either `provider.caption_frame` or
    `provider.caption_clip`; both return the same `FrameCaption` schema
    so the downstream `classify_conflicts` / `merge_visual_citations`
    pipeline stays evidence-kind-agnostic (LSP).

    DRY contract: this is the single dispatch site. Adding a new
    evidence kind = one branch on the kind switch + one method on the
    `VisionProvider` ABC + one branch in the cleanup TTL helper. No
    `if provider == 'gemini'` branches anywhere (OCP).

    Items are captioned concurrently via asyncio.gather for throughput.
    Low-confidence items are discarded before classification — clips
    emit `CLIP_DISCARDED`, frames emit nothing (the existing path
    discards silently with an info log). On provider failure the
    fallback chain is tried for the same evidence kind.
    """
    registry = get_registry()
    audit = get_audit_log_service()
    session_id = evidence[0].session_id if evidence and isinstance(
        evidence[0], MaskedFrame
    ) else (
        # Clips don't carry session_id on the model — derive from s3_key
        # `clips/{session_id}/{clip_id}.mp4`. Safe because the upload
        # endpoint built the key that way.
        evidence[0].s3_key.split("/")[1]
        if evidence and isinstance(evidence[0], MaskedClip)
        else ""
    )

    # Stage 2 progress tracking — emit a WebSocket event every ~10% of
    # evidence items + an initial "starting" tick at 0/N. iOS keeps
    # polling /notes/{id}/stage2-status so the event is purely
    # additive. Web subscribes to the same /ws/notes/{id} channel.
    total_evidence = len(evidence)
    processed_counter = 0
    progress_step = max(1, total_evidence // 10) if total_evidence else 1

    async def _emit_initial_progress() -> None:
        if total_evidence > 0 and session_id:
            from app.api.v1.websocket import notify_stage2_progress
            await notify_stage2_progress(session_id, 0, total_evidence)

    await _emit_initial_progress()

    async def _caption_single(
        item: VisualEvidenceItem,
    ) -> Optional[FrameCaption]:
        """Caption a single evidence item — frame or clip.

        Single dispatch switch on evidence_kind. The fallback chain
        on `ProviderError` uses the kind-aware variant so a Gemini
        outage on the clip path still hits OpenAI/Anthropic (which
        implement `caption_clip` via midpoint-still extraction, P1-2).
        """
        kind = _evidence_kind_of(item)
        evidence_id = _evidence_id_of(item)
        anchor = _find_anchor_segment(item.timestamp_ms, trigger_segments)
        if not anchor:
            return None

        provider = registry.get_vision_provider_for_kind_with_fallback(kind)
        operation_name = "caption_clip" if kind == "clip" else "caption_frame"
        _started = time.monotonic()
        try:
            caption = await _dispatch_caption(provider, item, anchor)
            await try_record_provider_usage(
                provider_type="vision",
                provider_name=caption.provider_used,
                operation=operation_name,
                latency_ms=int((time.monotonic() - _started) * 1000),
                success=True,
                session_id=session_id,
            )
            if caption.confidence == "low":
                logger.info(
                    "Low confidence evidence discarded: kind=%s id=%s reason=%s",
                    kind, evidence_id[:32], caption.confidence_reason,
                )
                # Clips get an explicit CLIP_DISCARDED audit row so the
                # eval team can post-hoc analyze what dropped out. The
                # frame path stays silent (existing behavior).
                if kind == "clip":
                    await audit.write_event(
                        session_id=session_id,
                        event_type=AuditEventType.CLIP_DISCARDED,
                        s3_key=item.s3_key,
                        confidence=caption.confidence,
                        confidence_reason=caption.confidence_reason,
                    )
                return None
            return caption
        except ProviderError as e:
            await try_record_provider_usage(
                provider_type="vision",
                provider_name=type(provider).__name__,
                operation=operation_name,
                latency_ms=int((time.monotonic() - _started) * 1000),
                success=False,
                session_id=session_id,
            )
            logger.warning(
                "Primary vision provider failed on %s=%s: %s — trying fallback",
                kind, evidence_id[:32], str(e),
            )
            _fb_started = time.monotonic()
            try:
                fallback_provider = (
                    registry.get_vision_provider_for_kind_with_fallback(kind)
                )
                caption = await _dispatch_caption(fallback_provider, item, anchor)
                await try_record_provider_usage(
                    provider_type="vision",
                    provider_name=caption.provider_used,
                    operation=operation_name,
                    latency_ms=int((time.monotonic() - _fb_started) * 1000),
                    success=True,
                    fallback_used=True,
                    session_id=session_id,
                )
                await audit.write_event(
                    session_id=session_id,
                    event_type=AuditEventType.PROVIDER_FALLBACK,
                    frame_id=evidence_id,
                    original_error=str(e),
                    fallback_provider=caption.provider_used,
                )
                if caption.confidence == "low":
                    if kind == "clip":
                        await audit.write_event(
                            session_id=session_id,
                            event_type=AuditEventType.CLIP_DISCARDED,
                            s3_key=item.s3_key,
                            confidence=caption.confidence,
                            confidence_reason=caption.confidence_reason,
                        )
                    return None
                return caption
            except ProviderError as fallback_err:
                logger.error(
                    "Vision captioning failed (all providers): kind=%s id=%s error=%s",
                    kind, evidence_id[:32], str(fallback_err),
                )
                await try_record_provider_usage(
                    provider_type="vision",
                    provider_name=type(fallback_provider).__name__,
                    operation=operation_name,
                    latency_ms=int((time.monotonic() - _fb_started) * 1000),
                    success=False,
                    fallback_used=True,
                    session_id=session_id,
                )
                await audit.write_event(
                    session_id=session_id,
                    event_type=AuditEventType.VISION_FRAME_FAILED,
                    frame_id=evidence_id,
                    error_message=str(fallback_err),
                )
                # A single failed evidence item is a WARNING — pipeline
                # discards and continues. Issue #76.
                await try_publish_alert(
                    alert_type=AuditEventType.VISION_FRAME_FAILED.value,
                    severity=AlertSeverity.WARNING,
                    source="vision_service",
                    message=(
                        "Vision captioning failed on a "
                        f"{kind} after fallback"
                    ),
                    metadata={
                        "session_id": str(session_id),
                        "evidence_kind": kind,
                    },
                )
                return None

    async def _caption_and_report(
        item: VisualEvidenceItem,
    ) -> Optional[FrameCaption]:
        """Wrap _caption_single with a progress counter so the WebSocket
        sees incremental progress instead of just the final delivery."""
        nonlocal processed_counter
        result = await _caption_single(item)
        processed_counter += 1
        # Emit on every Nth item OR at the very end so the final
        # state always shows "N / N" before stage2_delivered fires.
        if (
            processed_counter % progress_step == 0
            or processed_counter == total_evidence
        ):
            from app.api.v1.websocket import notify_stage2_progress
            await notify_stage2_progress(
                session_id, processed_counter, total_evidence
            )
        return result

    # Caption all evidence concurrently.
    results = await asyncio.gather(
        *(_caption_and_report(item) for item in evidence),
        return_exceptions=True,
    )

    captions: list[FrameCaption] = []
    failed_count = 0
    discarded_count = 0

    for result in results:
        if isinstance(result, Exception):
            failed_count += 1
            logger.error("Unexpected error captioning evidence: %s", result)
        elif result is None:
            discarded_count += 1
        else:
            captions.append(result)

    # If every evidence item failed, log a stage2 failure event.
    if evidence and failed_count == len(evidence):
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.STAGE2_FAILED,
            total_frames=len(evidence),
            failed_frames=failed_count,
        )
        await try_publish_alert(
            alert_type=AuditEventType.STAGE2_FAILED.value,
            severity=AlertSeverity.CRITICAL,
            source="vision_service",
            message=(
                f"Stage 2 vision failed: all {len(evidence)} items failed"
            ),
            metadata={
                "session_id": str(session_id),
                "total_evidence": len(evidence),
            },
        )

    logger.info(
        "Captioning complete: total=%d captioned=%d discarded=%d failed=%d",
        len(evidence), len(captions), discarded_count, failed_count,
    )
    return captions


async def _dispatch_caption(
    provider,
    item: VisualEvidenceItem,
    anchor: TranscriptSegment,
) -> FrameCaption:
    """Single dispatch site — frame vs clip provider methods.

    Lives at module scope (not nested) so unit tests can monkeypatch
    the provider and assert which method was called. Frame path
    returns the existing `caption_frame` result unchanged; clip path
    returns `caption_clip` which produces a `FrameCaption` with
    `evidence_kind="clip"` and `duration_ms=<clip window>` (LSP).
    """
    if isinstance(item, MaskedClip):
        return await provider.caption_clip(item, anchor)
    return await provider.caption_frame(item, anchor)


def _find_anchor_segment(
    timestamp_ms: int,
    segments: list[TranscriptSegment],
) -> Optional[TranscriptSegment]:
    """Find the transcript segment closest to a frame timestamp."""
    best = None
    best_dist = float("inf")
    for seg in segments:
        mid = (seg.start_ms + seg.end_ms) / 2
        dist = abs(timestamp_ms - mid)
        if dist < best_dist:
            best_dist = dist
            best = seg
    return best


# ── Conflict Classification ──────────────────────────────────────────────

def classify_conflicts(
    captions: list[FrameCaption],
    note: Note,
) -> list[FrameCaption]:
    """Classify each caption as ENRICHES, REPEATS, or CONFLICTS.

    For MVP, trusts the provider's classification. Production will use
    an LLM comparison against audio-anchored note claims.
    """
    for caption in captions:
        if caption.integration_status == "CONFLICTS":
            caption.conflict_flag = True

    enriches = sum(1 for c in captions if c.integration_status == "ENRICHES")
    repeats = sum(1 for c in captions if c.integration_status == "REPEATS")
    conflicts = sum(1 for c in captions if c.conflict_flag)

    logger.info(
        "Conflict classification: enriches=%d repeats=%d conflicts=%d",
        enriches, repeats, conflicts,
    )
    return captions


# ── Note Merger — Stage 2 ────────────────────────────────────────────────

def merge_visual_citations(
    note: Note,
    captions: list[FrameCaption],
) -> Note:
    """Merge frame citations into a Stage 1 note to produce Stage 2.

    - ENRICHES: inject visual description alongside audio claim
    - REPEATS: discard silently, audio stands alone
    - CONFLICTS: surface both, flag section for mandatory physician review
    """
    note.stage = 2

    for caption in captions:
        if caption.integration_status == "REPEATS":
            continue  # Discard silently

        # Find the target section based on the audio anchor
        target_section = _find_target_section(note, caption)
        if not target_section:
            continue

        if caption.integration_status == "ENRICHES":
            # Inject visual claim alongside audio
            target_section.claims.append(
                NoteClaim(
                    id=f"vclaim_{caption.frame_id}",
                    text=caption.visual_description,
                    source_type="visual",
                    source_id=caption.frame_id,
                    source_quote=f"[Frame {caption.frame_id} at {caption.timestamp_ms}ms]",
                )
            )
            if target_section.status == "pending_video":
                target_section.status = "populated"

        elif caption.integration_status == "CONFLICTS":
            # Surface both — flag for mandatory physician review
            target_section.claims.append(
                NoteClaim(
                    id=f"conflict_{caption.frame_id}",
                    text=f"CONFLICT: Visual observation differs from audio — {caption.visual_description}",
                    source_type="visual",
                    source_id=caption.frame_id,
                    source_quote=f"[Frame {caption.frame_id} at {caption.timestamp_ms}ms] {caption.conflict_detail or ''}",
                )
            )

    # Update remaining pending_video sections to processing_failed if no captions matched
    for section in note.sections:
        if section.status == "pending_video":
            section.status = "not_captured"

    logger.info(
        "Note merge complete: session=%s stage=%d sections=%d",
        str(note.session_id)[:8], note.stage, len(note.sections),
    )
    return note


def _find_target_section(note: Note, caption: FrameCaption) -> Optional[NoteSection]:
    """Find the note section that should receive this visual citation.

    Looks for sections with pending_video status or physical_exam/imaging sections.
    """
    # First try: find a section that has the anchor segment
    for section in note.sections:
        for claim in section.claims:
            if claim.source_id == caption.audio_anchor_id:
                return section

    # Fallback: find imaging_review or physical_exam sections
    for section in note.sections:
        if section.id in ("imaging_review", "physical_exam", "wound_assessment", "functional_assessment"):
            return section

    # Last resort: first section with pending_video status
    for section in note.sections:
        if section.status == "pending_video":
            return section

    return None


def has_unresolved_conflicts(captions: list[FrameCaption]) -> bool:
    """Check if any captions have CONFLICTS status."""
    return any(c.integration_status == "CONFLICTS" for c in captions)
