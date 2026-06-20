"""VID-03 — frame extraction at trigger windows (real ffmpeg; skip if absent)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

from app.modules.video_import.extraction import (
    extract_frame_at_ms,
    extract_frames_at_windows,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


def _make_video(path: str, seconds: int = 2) -> bool:
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=64x64:rate=10",
            "-pix_fmt", "yuv420p", path,
        ],
        capture_output=True,
    )
    return proc.returncode == 0 and os.path.getsize(path) > 0


@pytest.mark.asyncio
async def test_extract_single_frame() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "v.mp4")
        if not _make_video(video):
            pytest.skip("ffmpeg cannot build fixture")
        jpg = await extract_frame_at_ms(video, 500)
        assert isinstance(jpg, bytes) and len(jpg) > 0
        # JPEG SOI marker.
        assert jpg[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_frames_within_windows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "v.mp4")
        if not _make_video(video):
            pytest.skip("ffmpeg cannot build fixture")
        # Two windows; fps=2 → ~500ms spacing.
        windows = [(0, 1000), (1000, 1500)]
        frames = await extract_frames_at_windows(video, windows, fps=2)
        assert len(frames) > 0
        timestamps = [ts for ts, _ in frames]
        # Sorted + deduped + every timestamp lands inside some window.
        assert timestamps == sorted(set(timestamps))
        for ts in timestamps:
            assert any(lo <= ts <= hi for lo, hi in windows)
        for _ts, jpg in frames:
            assert jpg[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_empty_windows_yield_no_frames() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "v.mp4")
        if not _make_video(video):
            pytest.skip("ffmpeg cannot build fixture")
        assert await extract_frames_at_windows(video, [], fps=1) == []
