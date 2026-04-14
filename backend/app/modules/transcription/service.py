"""Transcription orchestration — upload audio, call provider, parse result.

Sequence: S3 upload → provider call via registry → trigger classifier →
PHI audit → audit log entries. Audio S3 object has < 1h TTL.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from app.core.retry import with_retry
from app.core.s3 import AUDIO_BUCKET, get_s3_client
from app.core.types import ProviderError, Transcript
from app.modules.audit_log.service import get_audit_log_service
from app.modules.config.provider_registry import get_registry

logger = logging.getLogger("aurion.transcription")


async def upload_audio_to_s3(
    audio_bytes: bytes,
    session_id: str | uuid.UUID,
) -> str:
    """Upload audio to S3. Returns the S3 object key.

    Audio bucket has < 1h TTL — objects auto-expire.
    S3 key never contains PHI.
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
            event_type="s3_upload_failed",
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
    # Step 1 — upload to S3
    s3_key = await upload_audio_to_s3(audio_bytes, session_id)

    # Step 2 — call provider via registry
    registry = get_registry()
    provider = registry.get_transcription_provider(override=provider_override)

    try:
        transcript = await provider.transcribe(audio_bytes, str(session_id))
        logger.info(
            "Transcription complete: session=%s provider=%s segments=%d",
            str(session_id),
            transcript.provider_used,
            len(transcript.segments),
        )
        return transcript
    except ProviderError:
        audit = get_audit_log_service()
        await audit.write_event(
            session_id=str(session_id),
            event_type="transcription_failed",
            error_message="Provider raised ProviderError",
        )
        raise
    except Exception as e:
        audit = get_audit_log_service()
        await audit.write_event(
            session_id=str(session_id),
            event_type="transcription_failed",
            error_message=str(e),
        )
        raise ProviderError(
            provider_override or "transcription",
            f"Transcription failed: {e}",
            e,
        )


async def delete_audio_from_s3(s3_key: str) -> bool:
    """Explicitly delete audio from S3 after transcription.

    This is in addition to the bucket TTL policy — belt and suspenders.
    """
    try:
        s3 = get_s3_client()
        s3.delete_object(Bucket=AUDIO_BUCKET, Key=s3_key)
        logger.info("Audio purged: key=%s", s3_key)
        return True
    except (BotoCoreError, ClientError) as e:
        logger.error("Audio purge failed: key=%s error=%s", s3_key, str(e))
        return False
