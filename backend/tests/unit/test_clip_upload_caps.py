"""Server-side clip upload bounds — duration ceiling + inline byte cap.

iOS extraction is already bounded by ``pipeline.clip_window_ms`` (schema
ceiling 30 s), so anything past these limits is a misbehaving or modified
client. Without the caps, a 5-minute MP4 posted to ``/clips/{session_id}``
sails into Stage 2, where it base64-inlines into a single Gemini
``generateContent`` request — over the ~20 MB inline request cap and the
per-minute token quota in one shot. These tests lock:

  * the ``duration_ms`` form field carries the ``le`` ceiling (FastAPI
    rejects with 422 before the handler runs);
  * an oversized body is rejected 413 BEFORE any S3 write;
  * a bounded clip still uploads.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import app.api.v1.clips as clips_mod
from app.api.v1.clips import _MAX_CLIP_BYTES, _MAX_CLIP_DURATION_MS, upload_clip


def _upload_file(body: bytes, content_type: str = "video/mp4") -> MagicMock:
    f = MagicMock()
    f.content_type = content_type
    f.read = AsyncMock(return_value=body)
    return f


def _call_kwargs(clip: MagicMock, duration_ms: int = 7000) -> dict:
    return {
        "session_id": uuid.uuid4(),
        "timestamp_ms": 14500,
        "duration_ms": duration_ms,
        "trigger_segment_id": "seg_001",
        "frames_total": 10,
        "frames_with_faces": 0,
        "masking_confirmed": True,
        "source": "trigger",
        "clip": clip,
        "user": MagicMock(),
        "db": AsyncMock(),
    }


def test_duration_form_field_carries_le_ceiling() -> None:
    """The route contract itself must bound duration_ms — FastAPI enforces
    the ``le`` at validation time (422), so a 5-minute ``duration_ms``
    never reaches the handler."""
    import inspect

    default = inspect.signature(upload_clip).parameters["duration_ms"].default
    le_values = [
        getattr(m, "le") for m in getattr(default, "metadata", []) if hasattr(m, "le")
    ]
    if getattr(default, "le", None) is not None:
        le_values.append(default.le)
    assert _MAX_CLIP_DURATION_MS in le_values
    # And the ceiling matches the schema bound on pipeline.clip_window_ms.
    assert _MAX_CLIP_DURATION_MS == 30_000


async def test_oversized_body_rejected_413_before_s3() -> None:
    oversized = b"x" * (_MAX_CLIP_BYTES + 1)
    fake_s3 = MagicMock()

    with patch.object(
        clips_mod, "get_owned_session_or_404", new_callable=AsyncMock
    ), patch.object(clips_mod, "get_s3_client", return_value=fake_s3), patch.object(
        clips_mod, "write_audit", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upload_clip(**_call_kwargs(_upload_file(oversized)))

    assert exc_info.value.status_code == 413
    fake_s3.put_object.assert_not_called()


async def test_bounded_clip_still_uploads() -> None:
    body = b"x" * 1024
    fake_s3 = MagicMock()

    with patch.object(
        clips_mod, "get_owned_session_or_404", new_callable=AsyncMock
    ), patch.object(clips_mod, "get_s3_client", return_value=fake_s3), patch.object(
        clips_mod, "write_audit", new_callable=AsyncMock
    ):
        response = await upload_clip(**_call_kwargs(_upload_file(body)))

    fake_s3.put_object.assert_called_once()
    assert response.bytes_uploaded == len(body)
