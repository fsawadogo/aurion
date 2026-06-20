"""VID-01 — ffmpeg audio extraction from an uploaded encounter video.

Runs the real ``ffmpeg`` binary (present in the backend image + dev shell).
Skips gracefully if ffmpeg is unavailable so a bare local environment
doesn't fail spuriously; CI runs inside the image where ffmpeg is installed.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile

import pytest

from app.modules.video_import.errors import VideoExtractionError
from app.modules.video_import.extraction import extract_audio

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


def _make_video_with_audio(path: str) -> bool:
    """Synthesize a 1s test video WITH an audio track. Returns True on
    success (the installed ffmpeg supports the needed encoders)."""
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", "-pix_fmt", "yuv420p", path,
        ],
        capture_output=True,
    )
    return proc.returncode == 0 and os.path.getsize(path) > 0


def _make_non_media_file(path: str) -> None:
    with open(path, "wb") as fh:
        fh.write(b"this is not a video file" * 10)


@pytest.mark.asyncio
async def test_extract_audio_produces_nonempty_wav() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "encounter.mp4")
        if not _make_video_with_audio(video):
            pytest.skip("installed ffmpeg lacks the encoders to build a fixture")
        out = os.path.join(tmp, "audio.wav")

        result = await extract_audio(video, out)

        assert result == out
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0


@pytest.mark.asyncio
async def test_extract_audio_raises_on_non_media_input() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bogus = os.path.join(tmp, "notavideo.mp4")
        _make_non_media_file(bogus)
        out = os.path.join(tmp, "audio.wav")

        with pytest.raises(VideoExtractionError) as exc:
            await extract_audio(bogus, out)

        # Bounded, PHI-free reason — never the input path or ffmpeg stderr.
        assert exc.value.reason.startswith("ffmpeg_exit_") or exc.value.reason == (
            "empty_audio_output"
        )
        assert tmp not in str(exc.value)


@pytest.mark.asyncio
async def test_extract_audio_missing_binary(monkeypatch) -> None:
    """A missing ffmpeg surfaces as a typed error, not a raw OSError."""

    async def _boom(*_a, **_k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    with pytest.raises(VideoExtractionError) as exc:
        await extract_audio("/tmp/x.mp4", "/tmp/x.wav")
    assert exc.value.reason == "ffmpeg_not_installed"
