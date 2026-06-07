"""Transcription orchestration — upload audio, call provider, parse result.

Sequence: S3 upload → provider call via registry → trigger classifier →
PHI audit → audit log entries. The audio S3 object is retained under the
bucket's lifecycle policy (~1 day; configurable in dev via
``media_retention_days``). Under the keep-full-window retention model the
object stays available for the full window and is removed only by that S3
lifecycle TTL or an on-demand Law 25 erasure — final-note approval does NOT
purge it (``feature_flags.media_review_retention_enabled`` only exposes the
audio-replay/download surfaces).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from app.core.audit_events import AuditEventType
from app.core.retry import with_retry
from app.core.s3 import AUDIO_BUCKET, get_s3_client
from app.core.types import ProviderError, Transcript, TranscriptSegment
from app.modules.alerts.service import AlertSeverity, try_publish_alert
from app.modules.audit_log.service import get_audit_log_service
from app.modules.config.provider_registry import get_registry
from app.modules.providers.usage_service import try_record_provider_usage

logger = logging.getLogger("aurion.transcription")


# ── Demo Mode ──────────────────────────────────────────────────────────────
#
# When AURION_DEMO_TRANSCRIPT=1, /transcription bypasses Whisper and returns
# a canned transcript matching the demo VO script (right knee pain / medial
# meniscus tear). Stage 1 note generation still runs — Gemini produces a real
# structured note from the canned text — so the resulting screens are not
# mocked, just seeded with predictable input.
#
# Used exclusively for capturing the demo video on the iOS Simulator, which
# has no microphone input. Safe in dev because the env var is unset by
# default; never set it in production.

DEMO_TRANSCRIPT_SEGMENTS: list[tuple[int, int, str, bool, Optional[str]]] = [
    (0, 4500,
     "Hi, what brings you in today?", False, None),
    (4500, 14000,
     "I've had pain in my right knee for about a year, "
     "ever since I twisted it playing soccer.", False, None),
    (14000, 22000,
     "It bothers me with walking and especially with sports.", False, None),
    (22000, 30000,
     "Let me have a look. I'm going to examine your knee now.", True, "physical_exam"),
    (30000, 38000,
     "There's a small effusion — some swelling here.", True, "physical_exam"),
    (38000, 48000,
     "Tenderness along the medial joint line. "
     "McMurray test is positive — pain on extremes of flexion.", True, "physical_exam"),
    (48000, 58000,
     "I'm pulling up your X-rays now.", True, "imaging_review"),
    (58000, 68000,
     "AP and lateral views show medial joint space narrowing on the right — "
     "consistent with mild osteoarthritis. Otherwise normal.", True, "imaging_review"),
    (68000, 78000,
     "Your MRI report shows a tear of the medial meniscus on the right.",
     True, "imaging_review"),
    (78000, 88000,
     "So we're looking at a medial meniscus tear with mild OA of the right knee.",
     False, None),
    (88000, 102000,
     "We can talk about conservative treatment first — physiotherapy and "
     "an injection — versus going to arthroscopy for a partial medial meniscectomy.",
     False, None),
    (102000, 118000,
     "Risks of arthroscopy include continued pain, infection, "
     "neurovascular injury, retear of the meniscus, and progression "
     "of the underlying arthritis. We'd discuss those in detail.",
     False, None),
]


def _demo_transcript(session_id: str) -> Transcript:
    """Build the canned demo transcript. Each segment has a stable id so
    Stage 1 claim citations are reproducible across re-runs."""
    return Transcript(
        session_id=session_id,
        provider_used="demo_canned",
        segments=[
            TranscriptSegment(
                id=f"seg_{i:03d}",
                start_ms=start,
                end_ms=end,
                text=text,
                speaker="physician" if i % 2 == 0 else "patient",
                is_visual_trigger=is_trigger,
                trigger_type=trigger_type,
            )
            for i, (start, end, text, is_trigger, trigger_type)
            in enumerate(DEMO_TRANSCRIPT_SEGMENTS)
        ],
    )


async def upload_audio_to_s3(
    audio_bytes: bytes,
    session_id: str | uuid.UUID,
) -> str:
    """Upload audio to S3. Returns the S3 object key.

    The audio bucket has a lifecycle policy (~1 day; configurable in dev
    via ``media_retention_days``). Under the keep-full-window retention
    model the object is retained for the full window and removed only by
    that S3 lifecycle TTL or an on-demand Law 25 erasure — final-note
    approval does NOT purge it. S3 key never contains PHI.
    """
    s3_key = f"audio/{session_id}/{uuid.uuid4()}.wav"
    try:
        s3 = get_s3_client()
        await with_retry(
            s3.put_object,
            Bucket=AUDIO_BUCKET,
            Key=s3_key,
            Body=audio_bytes,
            ContentType="audio/wav",
            max_retries=3,
            base_delay=1.0,
            operation="s3_put_object",
            session_id=str(session_id),
        )
        logger.info("Audio uploaded: session=%s key=%s", str(session_id), s3_key)
        return s3_key
    except (BotoCoreError, ClientError) as e:
        logger.error("S3 upload failed: session=%s error=%s", str(session_id), str(e))
        audit = get_audit_log_service()
        await audit.write_event(
            session_id=str(session_id),
            event_type=AuditEventType.S3_UPLOAD_FAILED,
            error_message=str(e),
        )
        raise ProviderError("s3", f"Audio upload failed: {e}", e)


async def transcribe_audio(
    audio_bytes: bytes,
    session_id: str | uuid.UUID,
    provider_override: Optional[str] = None,
) -> Transcript:
    """Run the full transcription pipeline.

    1. Upload audio to S3
    2. Call active transcription provider via registry
    3. Return timestamped transcript

    Trigger classification and PHI audit are run by the caller
    after receiving the transcript.
    """
    # Demo-mode short-circuit: when AURION_DEMO_TRANSCRIPT=1, return the
    # canned transcript without calling Whisper. Used for autonomous demo
    # capture on the iOS Simulator (no microphone). Skips S3 upload too —
    # there's no real audio worth retaining and skipping the upload makes
    # the take ~10s faster.
    if os.environ.get("AURION_DEMO_TRANSCRIPT") == "1":
        logger.info(
            "Demo transcript mode active — bypassing Whisper for session=%s",
            str(session_id),
        )
        return _demo_transcript(str(session_id))

    # Step 1 — upload to S3. The returned key isn't consumed downstream
    # (audit-log uses session_id, not the S3 key), so we discard it.
    await upload_audio_to_s3(audio_bytes, session_id)

    # Step 2 — call provider via registry
    registry = get_registry()
    provider = registry.get_transcription_provider(override=provider_override)

    _started = time.monotonic()
    try:
        transcript = await provider.transcribe(audio_bytes, str(session_id))
        logger.info(
            "Transcription complete: session=%s provider=%s segments=%d",
            str(session_id),
            transcript.provider_used,
            len(transcript.segments),
        )
        # Issue #73 — capture per-call telemetry; best-effort.
        await try_record_provider_usage(
            provider_type="transcription",
            provider_name=transcript.provider_used,
            operation="transcribe",
            latency_ms=int((time.monotonic() - _started) * 1000),
            success=True,
            session_id=session_id,
        )
        return transcript
    except ProviderError:
        audit = get_audit_log_service()
        await audit.write_event(
            session_id=str(session_id),
            event_type=AuditEventType.TRANSCRIPTION_FAILED,
            error_message="Provider raised ProviderError",
        )
        await try_record_provider_usage(
            provider_type="transcription",
            provider_name=provider_override or type(provider).__name__,
            operation="transcribe",
            latency_ms=int((time.monotonic() - _started) * 1000),
            success=False,
            session_id=session_id,
        )
        await try_publish_alert(
            alert_type=AuditEventType.TRANSCRIPTION_FAILED.value,
            severity=AlertSeverity.CRITICAL,
            source="transcription_service",
            message="Transcription provider raised ProviderError",
            metadata={"session_id": str(session_id)},
        )
        raise
    except Exception as e:
        audit = get_audit_log_service()
        await audit.write_event(
            session_id=str(session_id),
            event_type=AuditEventType.TRANSCRIPTION_FAILED,
            error_message=str(e),
        )
        await try_record_provider_usage(
            provider_type="transcription",
            provider_name=provider_override or type(provider).__name__,
            operation="transcribe",
            latency_ms=int((time.monotonic() - _started) * 1000),
            success=False,
            session_id=session_id,
        )
        await try_publish_alert(
            alert_type=AuditEventType.TRANSCRIPTION_FAILED.value,
            severity=AlertSeverity.CRITICAL,
            source="transcription_service",
            message="Transcription failed with unexpected exception",
            metadata={"session_id": str(session_id), "reason": str(e)[:200]},
        )
        raise ProviderError(
            provider_override or "transcription",
            f"Transcription failed: {e}",
            e,
        )
