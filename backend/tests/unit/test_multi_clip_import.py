"""Multi-clip video import — create flow, audio concat, and timeline offsets.

Sequential clips of ONE encounter are uploaded for a single session and merged
(audio concatenated in order → one transcript → one note). Gated by
feature_flags.multi_clip_import_enabled. CI runs only tests/unit, so the create
fan-out, the flag gate, and the extraction helpers are exercised here with
mocks; the live end-to-end concat lives in tests/integration.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import video_import as vi
from app.modules.video_import import extraction


def _cfg(multi: bool, video: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        feature_flags=SimpleNamespace(
            multi_clip_import_enabled=multi,
            video_import_enabled=video,
        )
    )


def _create_mocks():
    session = SimpleNamespace(id=uuid.uuid4(), import_source=None)
    job = SimpleNamespace(id=uuid.uuid4())
    return session, job


@pytest.mark.asyncio
async def test_create_multi_clip_returns_ordered_clips() -> None:
    body = vi.CreateVideoImportRequest(
        specialty="general", consent_attested=True, clip_count=3
    )
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    session, job = _create_mocks()
    create_job = AsyncMock(return_value=job)

    with patch.object(vi, "get_config", return_value=_cfg(multi=True)), \
        patch.object(vi, "create_session", AsyncMock(return_value=session)), \
        patch.object(vi, "confirm_consent", AsyncMock()), \
        patch.object(vi, "write_audit", AsyncMock()), \
        patch.object(vi.jobs, "create_job", create_job), \
        patch.object(
            vi, "generate_presigned_evidence_url", MagicMock(return_value="https://put")
        ):
        resp = await vi.create_video_import(body, None, user, db)

    # Ordered clips, one presigned PUT each, ordinal-named keys.
    assert resp.clips is not None and len(resp.clips) == 3
    assert [c.index for c in resp.clips] == [0, 1, 2]
    prefix = f"video-imports/{session.id}/"
    assert all(c.s3_key.startswith(prefix) for c in resp.clips)
    assert resp.clips[0].s3_key.split("/")[-1].startswith("00-")
    assert resp.clips[2].s3_key.split("/")[-1].startswith("02-")
    # Back-compat single fields point at the first clip.
    assert resp.s3_key == resp.clips[0].s3_key
    # The ordered key list is persisted on the job.
    kwargs = create_job.call_args.kwargs
    assert kwargs["raw_video_s3_keys"] == [c.s3_key for c in resp.clips]
    assert kwargs["raw_video_s3_key"] == resp.clips[0].s3_key


@pytest.mark.asyncio
async def test_create_multi_clip_rejected_when_flag_off() -> None:
    body = vi.CreateVideoImportRequest(
        specialty="general", consent_attested=True, clip_count=2
    )
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    session, job = _create_mocks()

    with patch.object(vi, "get_config", return_value=_cfg(multi=False)), \
        patch.object(vi, "create_session", AsyncMock(return_value=session)), \
        patch.object(vi, "confirm_consent", AsyncMock()), \
        patch.object(vi, "write_audit", AsyncMock()), \
        patch.object(vi.jobs, "create_job", AsyncMock(return_value=job)), \
        patch.object(
            vi, "generate_presigned_evidence_url", MagicMock(return_value="https://put")
        ):
        with pytest.raises(HTTPException) as exc:
            await vi.create_video_import(body, None, user, db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_single_clip_unchanged() -> None:
    body = vi.CreateVideoImportRequest(specialty="general", consent_attested=True)
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    session, job = _create_mocks()
    create_job = AsyncMock(return_value=job)

    with patch.object(vi, "get_config", return_value=_cfg(multi=False)), \
        patch.object(vi, "create_session", AsyncMock(return_value=session)), \
        patch.object(vi, "confirm_consent", AsyncMock()), \
        patch.object(vi, "write_audit", AsyncMock()), \
        patch.object(vi.jobs, "create_job", create_job), \
        patch.object(
            vi, "generate_presigned_evidence_url", MagicMock(return_value="https://put")
        ):
        resp = await vi.create_video_import(body, None, user, db)

    # No clips list; single-clip behaviour preserved (no ordinal prefix).
    assert resp.clips is None
    assert create_job.call_args.kwargs.get("raw_video_s3_keys") is None


def test_wav_duration_ms_from_size(tmp_path) -> None:
    # 16 kHz mono s16le → 32 bytes/ms. 44-byte header + 32000 sample bytes = 1s.
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"\x00" * (44 + 32000))
    assert extraction.wav_duration_ms(str(wav)) == 1000


def test_wav_duration_ms_missing_file_is_zero() -> None:
    assert extraction.wav_duration_ms("/no/such/file.wav") == 0


@pytest.mark.asyncio
async def test_concat_audio_single_returns_path() -> None:
    # One clip needs no concat — returned as-is (no ffmpeg shell-out).
    with patch.object(extraction, "_run_ffmpeg", AsyncMock()) as ff:
        out = await extraction.concat_audio(["/tmp/only.wav"], "/tmp/out.wav")
    assert out == "/tmp/only.wav"
    ff.assert_not_awaited()


@pytest.mark.asyncio
async def test_concat_audio_multiple_invokes_ffmpeg_concat(tmp_path) -> None:
    out_path = str(tmp_path / "combined.wav")

    async def fake_ffmpeg(args):
        # ffmpeg writes the output; simulate a non-empty result + assert the
        # concat demuxer is used with a list file.
        assert "concat" in args and "-safe" in args
        with open(out_path, "wb") as fh:
            fh.write(b"\x00" * 100)

    with patch.object(extraction, "_run_ffmpeg", side_effect=fake_ffmpeg):
        out = await extraction.concat_audio(
            [str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], out_path
        )
    assert out == out_path
    assert os.path.getsize(out_path) > 0


@pytest.mark.asyncio
async def test_concat_audio_empty_raises() -> None:
    with pytest.raises(extraction.VideoExtractionError):
        await extraction.concat_audio([], "/tmp/out.wav")
