"""VID-11 — presigned S3 multipart upload endpoints (mocked S3, no DB)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import video_import as vi


def _s3() -> MagicMock:
    c = MagicMock()
    c.create_multipart_upload = MagicMock(return_value={"UploadId": "upl_1"})
    c.generate_presigned_url = MagicMock(return_value="https://s3/part")
    c.complete_multipart_upload = MagicMock(return_value={})
    c.abort_multipart_upload = MagicMock(return_value={})
    return c


def test_start_multipart_computes_parts() -> None:
    s3 = _s3()
    with patch.object(vi, "get_s3_client", MagicMock(return_value=s3)):
        # 70 MB with a 32 MB part size → ceil(70/32) = 3 parts.
        resp = vi.start_multipart("video-imports/x/v.mp4", 70 * 1024 * 1024)
    assert resp.upload_id == "upl_1"
    assert len(resp.parts) == 3
    assert [p.part_number for p in resp.parts] == [1, 2, 3]
    assert resp.part_size == vi._MULTIPART_PART_SIZE
    _, kwargs = s3.create_multipart_upload.call_args
    assert kwargs["Bucket"] == vi.VIDEO_IMPORTS_BUCKET
    assert kwargs["Key"] == "video-imports/x/v.mp4"


def test_start_multipart_single_part_for_small_file() -> None:
    s3 = _s3()
    with patch.object(vi, "get_s3_client", MagicMock(return_value=s3)):
        resp = vi.start_multipart("k", 10)
    assert len(resp.parts) == 1


def test_start_multipart_rejects_too_many_parts() -> None:
    s3 = _s3()
    huge = vi._MULTIPART_PART_SIZE * (vi._S3_MAX_PARTS + 5)
    with patch.object(vi, "get_s3_client", MagicMock(return_value=s3)):
        with pytest.raises(HTTPException) as exc:
            vi.start_multipart("k", huge)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_complete_sorts_parts_and_calls_s3() -> None:
    s3 = _s3()
    sid = uuid.uuid4()
    body = vi.CompleteMultipartRequest(
        upload_id="upl_1",
        parts=[
            vi.CompletedPart(part_number=2, etag="e2"),
            vi.CompletedPart(part_number=1, etag="e1"),
        ],
    )
    with patch.object(vi, "get_owned_session_or_404", AsyncMock()), \
        patch.object(vi, "_job_key_or_404", AsyncMock(return_value=(SimpleNamespace(), "k"))), \
        patch.object(vi, "get_s3_client", MagicMock(return_value=s3)):
        out = await vi.complete_multipart_upload(
            sid, body, None, SimpleNamespace(user_id=uuid.uuid4()), AsyncMock()
        )
    assert out == {"status": "uploaded"}
    _, kwargs = s3.complete_multipart_upload.call_args
    # Parts must be sorted ascending by part_number for S3.
    assert kwargs["MultipartUpload"]["Parts"] == [
        {"ETag": "e1", "PartNumber": 1},
        {"ETag": "e2", "PartNumber": 2},
    ]


@pytest.mark.asyncio
async def test_abort_calls_s3() -> None:
    s3 = _s3()
    body = vi.AbortMultipartRequest(upload_id="upl_1")
    with patch.object(vi, "get_owned_session_or_404", AsyncMock()), \
        patch.object(vi, "_job_key_or_404", AsyncMock(return_value=(SimpleNamespace(), "k"))), \
        patch.object(vi, "get_s3_client", MagicMock(return_value=s3)):
        out = await vi.abort_multipart_upload(
            uuid.uuid4(), body, None, SimpleNamespace(user_id=uuid.uuid4()), AsyncMock()
        )
    assert out == {"status": "aborted"}
    s3.abort_multipart_upload.assert_called_once()
