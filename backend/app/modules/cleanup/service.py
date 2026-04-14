"""Data lifecycle cleanup -- purge raw audio after transcription, temp frames
after export, migrate eval frames to secure bucket.

Every purge action is logged to the immutable DynamoDB audit trail.
Bucket names and AWS endpoint are read from environment variables.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.retry import with_retry
from app.modules.audit_log.service import get_audit_log_service

logger = logging.getLogger("aurion.cleanup")

_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
_AUDIO_BUCKET = os.getenv("AUDIO_S3_BUCKET", "aurion-audio-local")
_FRAMES_BUCKET = os.getenv("FRAMES_S3_BUCKET", "aurion-frames-local")
_EVAL_BUCKET = os.getenv("EVAL_S3_BUCKET", "aurion-eval-local")


def _get_s3_client():
    """Create a boto3 S3 client with optional endpoint override for LocalStack."""
    kwargs: dict[str, Any] = {"region_name": _REGION}
    if _ENDPOINT_URL:
        kwargs["endpoint_url"] = _ENDPOINT_URL
    return boto3.client("s3", **kwargs)


async def purge_audio(session_id: str, s3_key: str) -> None:
    """Delete a raw audio object from S3 after transcription and log the purge.

    Args:
        session_id: The session this audio belongs to.
        s3_key: The S3 object key to delete from the audio bucket.
    """
    client = _get_s3_client()
    audit = get_audit_log_service()

    logger.info(
        "Purging audio: session=%s bucket=%s key=%s",
        session_id,
        _AUDIO_BUCKET,
        s3_key,
    )

    try:
        await with_retry(
            client.delete_object,
            Bucket=_AUDIO_BUCKET,
            Key=s3_key,
            max_retries=3,
            base_delay=1.0,
            operation="s3_delete_audio",
            session_id=session_id,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "Failed to purge audio: session=%s key=%s error=%s",
            session_id,
            s3_key,
            str(exc),
        )
        await audit.write_event(
            session_id=session_id,
            event_type="cleanup_partial_failure",
            bucket=_AUDIO_BUCKET,
            s3_key=s3_key,
            error_message=str(exc),
        )
        raise

    await audit.write_event(
        session_id=session_id,
        event_type="audio_purged",
        bucket=_AUDIO_BUCKET,
        s3_key=s3_key,
    )

    logger.info("Audio purged successfully: session=%s key=%s", session_id, s3_key)


async def purge_frames(session_id: str) -> None:
    """Delete all temporary frames for a session from S3 after export.

    Lists all objects under the session prefix in the frames bucket and
    deletes them in a single batch request. Logs ``frames_purged`` to
    the audit trail.

    Args:
        session_id: The session whose frames should be purged.
    """
    client = _get_s3_client()
    audit = get_audit_log_service()

    prefix = f"{session_id}/"
    logger.info(
        "Purging frames: session=%s bucket=%s prefix=%s",
        session_id,
        _FRAMES_BUCKET,
        prefix,
    )

    keys_deleted: list[str] = []
    failed_keys: list[str] = []

    try:
        # List all objects under the session prefix
        paginator = client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=_FRAMES_BUCKET, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue

            delete_request = {
                "Objects": [{"Key": obj["Key"]} for obj in objects],
                "Quiet": True,
            }
            try:
                await with_retry(
                    client.delete_objects,
                    Bucket=_FRAMES_BUCKET,
                    Delete=delete_request,
                    max_retries=3,
                    base_delay=1.0,
                    operation="s3_delete_frames",
                    session_id=session_id,
                )
                keys_deleted.extend(obj["Key"] for obj in objects)
            except (BotoCoreError, ClientError) as batch_exc:
                logger.error(
                    "Failed to delete frame batch: session=%s error=%s",
                    session_id,
                    str(batch_exc),
                )
                failed_keys.extend(obj["Key"] for obj in objects)

    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "Failed to purge frames: session=%s error=%s",
            session_id,
            str(exc),
        )
        raise

    if failed_keys:
        await audit.write_event(
            session_id=session_id,
            event_type="cleanup_partial_failure",
            bucket=_FRAMES_BUCKET,
            failed_count=len(failed_keys),
        )

    await audit.write_event(
        session_id=session_id,
        event_type="frames_purged",
        bucket=_FRAMES_BUCKET,
        frame_count=len(keys_deleted),
    )

    logger.info(
        "Frames purged: session=%s deleted=%d failed=%d",
        session_id,
        len(keys_deleted),
        len(failed_keys),
    )


async def migrate_eval_frames(session_id: str) -> None:
    """Copy masked evaluation frames from the frames bucket to the secure eval
    bucket, then delete the originals from the frames bucket.

    The eval bucket has separate access controls and longer retention
    for the internal evaluation team.

    Args:
        session_id: The session whose frames should be migrated.
    """
    client = _get_s3_client()
    audit = get_audit_log_service()

    prefix = f"{session_id}/"
    logger.info(
        "Migrating eval frames: session=%s from=%s to=%s",
        session_id,
        _FRAMES_BUCKET,
        _EVAL_BUCKET,
    )

    migrated_keys: list[str] = []
    failed_keys: list[str] = []

    try:
        paginator = client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=_FRAMES_BUCKET, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue

            for obj in objects:
                source_key = obj["Key"]
                copy_source = {"Bucket": _FRAMES_BUCKET, "Key": source_key}

                try:
                    # Copy to eval bucket preserving the key structure
                    await with_retry(
                        client.copy_object,
                        CopySource=copy_source,
                        Bucket=_EVAL_BUCKET,
                        Key=source_key,
                        max_retries=3,
                        base_delay=1.0,
                        operation="s3_copy_eval_frame",
                        session_id=session_id,
                    )

                    # Verify destination object exists before deleting source
                    await with_retry(
                        client.head_object,
                        Bucket=_EVAL_BUCKET,
                        Key=source_key,
                        max_retries=2,
                        base_delay=0.5,
                        operation="s3_verify_eval_copy",
                        session_id=session_id,
                    )

                    migrated_keys.append(source_key)
                except (BotoCoreError, ClientError) as copy_exc:
                    logger.error(
                        "Failed to migrate frame: session=%s key=%s error=%s",
                        session_id,
                        source_key,
                        str(copy_exc),
                    )
                    failed_keys.append(source_key)

        # Delete originals from the frames bucket only for verified copies
        if migrated_keys:
            delete_request = {
                "Objects": [{"Key": key} for key in migrated_keys],
                "Quiet": True,
            }
            await with_retry(
                client.delete_objects,
                Bucket=_FRAMES_BUCKET,
                Delete=delete_request,
                max_retries=3,
                base_delay=1.0,
                operation="s3_delete_migrated_frames",
                session_id=session_id,
            )

    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "Failed to migrate eval frames: session=%s error=%s",
            session_id,
            str(exc),
        )
        raise

    if failed_keys:
        await audit.write_event(
            session_id=session_id,
            event_type="cleanup_partial_failure",
            bucket=_FRAMES_BUCKET,
            failed_count=len(failed_keys),
        )

    await audit.write_event(
        session_id=session_id,
        event_type="eval_frames_migrated",
        source_bucket=_FRAMES_BUCKET,
        dest_bucket=_EVAL_BUCKET,
        frame_count=len(migrated_keys),
    )

    logger.info(
        "Eval frames migrated: session=%s migrated=%d failed=%d",
        session_id,
        len(migrated_keys),
        len(failed_keys),
    )


async def verify_purge(session_id: str) -> bool:
    """Verify all audio and frame files for a session have been purged.

    Checks both the audio and frames S3 buckets for any remaining objects
    under the session prefix. Returns True only if both are empty.
    """
    client = _get_s3_client()

    for bucket, prefix in [
        (_AUDIO_BUCKET, f"audio/{session_id}/"),
        (_FRAMES_BUCKET, f"{session_id}/"),
    ]:
        try:
            response = client.list_objects_v2(
                Bucket=bucket, Prefix=prefix, MaxKeys=1
            )
            if response.get("Contents"):
                logger.warning(
                    "Purge verification failed: session=%s bucket=%s — objects remain",
                    session_id,
                    bucket,
                )
                return False
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "Purge verification error: session=%s bucket=%s error=%s",
                session_id,
                bucket,
                str(exc),
            )
            return False

    logger.info("Purge verified: session=%s — all buckets empty", session_id)
    return True
