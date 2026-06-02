"""Data lifecycle cleanup -- purge raw audio after transcription, temp visual
evidence (frames + clips) after export, migrate eval evidence to secure
bucket.

Every purge action is logged to the immutable DynamoDB audit trail.
Bucket names and AWS endpoint are read from environment variables.

Dual-mode evidence (P1-3): both frame stills and video clips live in
the same S3 bucket (`FRAMES_BUCKET`) under sibling prefixes —
`frames/{session_id}/{ts}.jpg` and `clips/{session_id}/{clip_id}.mp4`.
The purge + migrate helpers parameterise on a `prefix` string so a
single core implementation covers both kinds; the public
`purge_frames` / `purge_clips` / `purge_all_evidence` callers keep
narrow names so the audit trail and call sites stay self-documenting.
"""

from __future__ import annotations

import logging
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError

from app.core.audit_events import AuditEventType
from app.core.retry import with_retry
from app.core.s3 import AUDIO_BUCKET, EVAL_BUCKET, FRAMES_BUCKET, get_s3_client
from app.modules.audit_log.service import get_audit_log_service

logger = logging.getLogger("aurion.cleanup")

# Evidence kind → S3 prefix shape. Single source of truth so any future
# evidence kind (e.g. screen captures, depth maps) lands as one new
# entry, not a third copy of the purge/migrate logic.
EvidenceKind = Literal["frame", "clip"]

_EVIDENCE_PREFIX_TEMPLATE: dict[EvidenceKind, str] = {
    "frame": "{session_id}/",  # historical baseline — used to be flat
    "clip": "clips/{session_id}/",
}


def _evidence_prefix(kind: EvidenceKind, session_id: str) -> str:
    return _EVIDENCE_PREFIX_TEMPLATE[kind].format(session_id=session_id)


async def purge_audio(session_id: str, s3_key: str) -> None:
    """Delete a raw audio object from S3 after transcription and log the purge.

    Args:
        session_id: The session this audio belongs to.
        s3_key: The S3 object key to delete from the audio bucket.
    """
    client = get_s3_client()
    audit = get_audit_log_service()

    logger.info(
        "Purging audio: session=%s bucket=%s key=%s",
        session_id,
        AUDIO_BUCKET,
        s3_key,
    )

    try:
        await with_retry(
            client.delete_object,
            Bucket=AUDIO_BUCKET,
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
            event_type=AuditEventType.CLEANUP_PARTIAL_FAILURE,
            bucket=AUDIO_BUCKET,
            s3_key=s3_key,
            error_message=str(exc),
        )
        raise

    await audit.write_event(
        session_id=session_id,
        event_type=AuditEventType.AUDIO_PURGED,
        bucket=AUDIO_BUCKET,
        s3_key=s3_key,
    )

    logger.info("Audio purged successfully: session=%s key=%s", session_id, s3_key)


async def _purge_evidence_under_prefix(
    session_id: str,
    prefix: str,
    operation_label: str,
) -> tuple[list[str], list[str]]:
    """Delete every S3 object under ``prefix`` in the frames bucket.

    Core helper shared by `purge_frames` + `purge_clips` (DRY rule from
    §6c). Returns ``(deleted_keys, failed_keys)`` so the caller can
    decide which audit event to emit and at what severity. Does NOT
    write the audit event itself — that lets `purge_all_evidence`
    aggregate one summary row instead of two.

    The ``operation_label`` is forwarded to ``with_retry`` so the retry
    telemetry distinguishes frame vs clip purges in the dashboards.
    """
    client = get_s3_client()
    keys_deleted: list[str] = []
    failed_keys: list[str] = []

    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=FRAMES_BUCKET, Prefix=prefix):
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
                    Bucket=FRAMES_BUCKET,
                    Delete=delete_request,
                    max_retries=3,
                    base_delay=1.0,
                    operation=operation_label,
                    session_id=session_id,
                )
                keys_deleted.extend(obj["Key"] for obj in objects)
            except (BotoCoreError, ClientError) as batch_exc:
                logger.error(
                    "Failed to delete evidence batch: session=%s prefix=%s error=%s",
                    str(session_id)[:8],
                    prefix,
                    str(batch_exc),
                )
                failed_keys.extend(obj["Key"] for obj in objects)
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "Failed to purge evidence: session=%s prefix=%s error=%s",
            str(session_id)[:8],
            prefix,
            str(exc),
        )
        raise

    return keys_deleted, failed_keys


async def purge_frames(session_id: str) -> None:
    """Delete all temporary frames for a session from S3 after export.

    Lists every object under the historical session prefix in the
    frames bucket and batch-deletes them. Logs ``frames_purged`` to
    the audit trail.

    DRY: the heavy lifting lives in `_purge_evidence_under_prefix`; this
    function owns the audit emission + log line. Same shape as the
    new `purge_clips`.

    Args:
        session_id: The session whose frames should be purged.
    """
    audit = get_audit_log_service()
    prefix = _evidence_prefix("frame", session_id)
    logger.info(
        "Purging frames: session=%s bucket=%s prefix=%s",
        str(session_id)[:8],
        FRAMES_BUCKET,
        prefix,
    )

    keys_deleted, failed_keys = await _purge_evidence_under_prefix(
        session_id=session_id,
        prefix=prefix,
        operation_label="s3_delete_frames",
    )

    if failed_keys:
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.CLEANUP_PARTIAL_FAILURE,
            bucket=FRAMES_BUCKET,
            failed_count=len(failed_keys),
        )

    await audit.write_event(
        session_id=session_id,
        event_type=AuditEventType.FRAMES_PURGED,
        bucket=FRAMES_BUCKET,
        frame_count=len(keys_deleted),
    )

    logger.info(
        "Frames purged: session=%s deleted=%d failed=%d",
        str(session_id)[:8],
        len(keys_deleted),
        len(failed_keys),
    )


async def purge_clips(session_id: str) -> None:
    """Delete all temporary clips for a session from S3 after export.

    Sibling of `purge_frames` for the dual-mode clip path. Same 24h
    post-Stage-2 TTL pattern, same eval-tagged migration semantics
    (handled by `migrate_eval_clips`). Emits `FRAMES_PURGED` against
    the same bucket — the audit row's `frame_count` is the total
    objects deleted (frame_count is a misnomer post-P1-3 but kept for
    schema stability; the kwarg whitelist already names it that way).

    Tolerates the "no clips ever uploaded" case by emitting a 0-count
    audit row rather than skipping — the audit trail should show the
    purge attempt even when there's nothing to clean.

    Args:
        session_id: The session whose clips should be purged.
    """
    audit = get_audit_log_service()
    prefix = _evidence_prefix("clip", session_id)
    logger.info(
        "Purging clips: session=%s bucket=%s prefix=%s",
        str(session_id)[:8],
        FRAMES_BUCKET,
        prefix,
    )

    keys_deleted, failed_keys = await _purge_evidence_under_prefix(
        session_id=session_id,
        prefix=prefix,
        operation_label="s3_delete_clips",
    )

    if failed_keys:
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.CLEANUP_PARTIAL_FAILURE,
            bucket=FRAMES_BUCKET,
            failed_count=len(failed_keys),
        )

    await audit.write_event(
        session_id=session_id,
        event_type=AuditEventType.FRAMES_PURGED,
        bucket=FRAMES_BUCKET,
        frame_count=len(keys_deleted),
    )

    logger.info(
        "Clips purged: session=%s deleted=%d failed=%d",
        str(session_id)[:8],
        len(keys_deleted),
        len(failed_keys),
    )


async def purge_all_evidence(session_id: str) -> None:
    """Convenience helper — purge frames + clips in one call.

    Used by `export/service.py` when the session is exported and every
    piece of visual evidence becomes eligible for purge. Runs frame +
    clip purges sequentially (deliberately, not concurrently: both go
    through the same bucket and pagination concurrency would re-list
    each other's deletes). Either failing is fatal to the other —
    matches the existing `purge_frames` semantics.
    """
    await purge_frames(session_id)
    await purge_clips(session_id)


async def _migrate_evidence_under_prefix(
    session_id: str,
    prefix: str,
    copy_operation_label: str,
    verify_operation_label: str,
    delete_operation_label: str,
) -> tuple[list[str], list[str]]:
    """Copy + verify + delete every S3 object under ``prefix`` from
    `FRAMES_BUCKET` to `EVAL_BUCKET`.

    Core helper shared by `migrate_eval_frames` + `migrate_eval_clips`
    (DRY rule from §6c). Returns ``(migrated_keys, failed_keys)`` so
    callers can decide which audit event to emit.
    """
    client = get_s3_client()
    migrated_keys: list[str] = []
    failed_keys: list[str] = []

    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=FRAMES_BUCKET, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            for obj in objects:
                source_key = obj["Key"]
                copy_source = {"Bucket": FRAMES_BUCKET, "Key": source_key}
                try:
                    # Copy to eval bucket preserving the key structure.
                    await with_retry(
                        client.copy_object,
                        CopySource=copy_source,
                        Bucket=EVAL_BUCKET,
                        Key=source_key,
                        max_retries=3,
                        base_delay=1.0,
                        operation=copy_operation_label,
                        session_id=session_id,
                    )
                    # Verify destination before deleting source.
                    await with_retry(
                        client.head_object,
                        Bucket=EVAL_BUCKET,
                        Key=source_key,
                        max_retries=2,
                        base_delay=0.5,
                        operation=verify_operation_label,
                        session_id=session_id,
                    )
                    migrated_keys.append(source_key)
                except (BotoCoreError, ClientError) as copy_exc:
                    logger.error(
                        "Failed to migrate evidence: session=%s key=%s error=%s",
                        str(session_id)[:8],
                        source_key,
                        str(copy_exc),
                    )
                    failed_keys.append(source_key)
        # Delete originals only for verified copies.
        if migrated_keys:
            delete_request = {
                "Objects": [{"Key": key} for key in migrated_keys],
                "Quiet": True,
            }
            await with_retry(
                client.delete_objects,
                Bucket=FRAMES_BUCKET,
                Delete=delete_request,
                max_retries=3,
                base_delay=1.0,
                operation=delete_operation_label,
                session_id=session_id,
            )
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "Failed to migrate evidence: session=%s prefix=%s error=%s",
            str(session_id)[:8],
            prefix,
            str(exc),
        )
        raise

    return migrated_keys, failed_keys


async def migrate_eval_frames(session_id: str) -> None:
    """Copy masked evaluation frames from the frames bucket to the
    secure eval bucket, then delete the originals.

    The eval bucket has separate access controls and longer retention
    for the internal evaluation team.

    DRY: heavy lifting lives in `_migrate_evidence_under_prefix`; this
    function owns the audit emission. Same shape as
    `migrate_eval_clips`.

    Args:
        session_id: The session whose frames should be migrated.
    """
    audit = get_audit_log_service()
    prefix = _evidence_prefix("frame", session_id)
    logger.info(
        "Migrating eval frames: session=%s from=%s to=%s",
        str(session_id)[:8],
        FRAMES_BUCKET,
        EVAL_BUCKET,
    )

    migrated_keys, failed_keys = await _migrate_evidence_under_prefix(
        session_id=session_id,
        prefix=prefix,
        copy_operation_label="s3_copy_eval_frame",
        verify_operation_label="s3_verify_eval_copy",
        delete_operation_label="s3_delete_migrated_frames",
    )

    if failed_keys:
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.CLEANUP_PARTIAL_FAILURE,
            bucket=FRAMES_BUCKET,
            failed_count=len(failed_keys),
        )

    await audit.write_event(
        session_id=session_id,
        event_type=AuditEventType.EVAL_FRAMES_MIGRATED,
        source_bucket=FRAMES_BUCKET,
        dest_bucket=EVAL_BUCKET,
        frame_count=len(migrated_keys),
    )

    logger.info(
        "Eval frames migrated: session=%s migrated=%d failed=%d",
        str(session_id)[:8],
        len(migrated_keys),
        len(failed_keys),
    )


async def migrate_eval_clips(session_id: str) -> None:
    """Sibling of `migrate_eval_frames` for the clip path.

    Same source/dest buckets, same verify-before-delete contract.
    The eval team gets long-term retention for clip evidence so the
    `@provider-evaluator` subagent can replay sessions on motion-heavy
    triggers (the whole point of P1-3 / P1-4).
    """
    audit = get_audit_log_service()
    prefix = _evidence_prefix("clip", session_id)
    logger.info(
        "Migrating eval clips: session=%s from=%s to=%s",
        str(session_id)[:8],
        FRAMES_BUCKET,
        EVAL_BUCKET,
    )

    migrated_keys, failed_keys = await _migrate_evidence_under_prefix(
        session_id=session_id,
        prefix=prefix,
        copy_operation_label="s3_copy_eval_clip",
        verify_operation_label="s3_verify_eval_clip_copy",
        delete_operation_label="s3_delete_migrated_clips",
    )

    if failed_keys:
        await audit.write_event(
            session_id=session_id,
            event_type=AuditEventType.CLEANUP_PARTIAL_FAILURE,
            bucket=FRAMES_BUCKET,
            failed_count=len(failed_keys),
        )

    await audit.write_event(
        session_id=session_id,
        event_type=AuditEventType.EVAL_FRAMES_MIGRATED,
        source_bucket=FRAMES_BUCKET,
        dest_bucket=EVAL_BUCKET,
        frame_count=len(migrated_keys),
    )

    logger.info(
        "Eval clips migrated: session=%s migrated=%d failed=%d",
        str(session_id)[:8],
        len(migrated_keys),
        len(failed_keys),
    )


async def verify_purge(session_id: str) -> bool:
    """Verify all audio, frame, and clip files for a session are purged.

    Checks audio + frames + clips S3 prefixes for any remaining objects.
    Returns True only if all three are empty. P1-3 extended the check
    to cover the clip prefix; before this PR `verify_purge` would
    pass on a session whose clips hadn't been touched, giving a
    false-positive purge-confirmation row in the audit trail.
    """
    client = get_s3_client()

    checks: list[tuple[str, str]] = [
        (AUDIO_BUCKET, f"audio/{session_id}/"),
        (FRAMES_BUCKET, _evidence_prefix("frame", session_id)),
        (FRAMES_BUCKET, _evidence_prefix("clip", session_id)),
    ]

    for bucket, prefix in checks:
        try:
            response = client.list_objects_v2(
                Bucket=bucket, Prefix=prefix, MaxKeys=1
            )
            if response.get("Contents"):
                logger.warning(
                    "Purge verification failed: session=%s bucket=%s — objects remain",
                    str(session_id)[:8],
                    bucket,
                )
                return False
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "Purge verification error: session=%s bucket=%s error=%s",
                str(session_id)[:8],
                bucket,
                str(exc),
            )
            return False

    logger.info(
        "Purge verified: session=%s — all prefixes empty", str(session_id)[:8]
    )
    return True
