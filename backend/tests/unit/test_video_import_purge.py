"""VID-01 — raw-video purge after extraction.

Mirrors ``test_cleanup`` (mocked S3 client + audit, no LocalStack). Proves
``purge_raw_video`` deletes from the video-imports bucket and emits
``RAW_VIDEO_PURGED`` on success, and emits ``CLEANUP_PARTIAL_FAILURE`` +
re-raises on a delete failure — the fail-loud contract that keeps the
orchestrator from proceeding while an unmasked video lingers.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.audit_events import AuditEventType
from app.core.s3 import VIDEO_IMPORTS_BUCKET
from app.modules.cleanup import service as cleanup


def _mock_audit() -> AsyncMock:
    audit = AsyncMock()
    audit.write_event = AsyncMock(return_value={})
    return audit


@pytest.mark.asyncio
async def test_purge_raw_video_deletes_and_audits() -> None:
    sid = str(uuid.uuid4())
    key = f"video-imports/{sid}/abc123.mp4"
    client = MagicMock()
    client.delete_object = MagicMock(return_value={})
    audit = _mock_audit()

    with patch.object(cleanup, "get_s3_client", return_value=client), patch.object(
        cleanup, "get_audit_log_service", return_value=audit
    ):
        await cleanup.purge_raw_video(sid, key)

    # Deleted from the dedicated video-imports bucket with the exact key.
    _, kwargs = client.delete_object.call_args
    assert kwargs["Bucket"] == VIDEO_IMPORTS_BUCKET
    assert kwargs["Key"] == key

    # Success audit row is RAW_VIDEO_PURGED with bucket + key only.
    audit.write_event.assert_awaited_once()
    _, ev = audit.write_event.call_args
    assert ev["event_type"] == AuditEventType.RAW_VIDEO_PURGED
    assert ev["bucket"] == VIDEO_IMPORTS_BUCKET
    assert ev["s3_key"] == key


@pytest.mark.asyncio
async def test_purge_raw_video_failure_audits_partial_and_raises() -> None:
    sid = str(uuid.uuid4())
    key = f"video-imports/{sid}/abc123.mp4"
    client = MagicMock()
    client.delete_object = MagicMock(
        side_effect=ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
    )
    audit = _mock_audit()

    with patch.object(cleanup, "get_s3_client", return_value=client), patch.object(
        cleanup, "get_audit_log_service", return_value=audit
    ):
        with pytest.raises(ClientError):
            await cleanup.purge_raw_video(sid, key)

    # Fail-loud: a CLEANUP_PARTIAL_FAILURE row is written before re-raising.
    _, ev = audit.write_event.call_args
    assert ev["event_type"] == AuditEventType.CLEANUP_PARTIAL_FAILURE
    assert ev["bucket"] == VIDEO_IMPORTS_BUCKET
