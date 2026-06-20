"""ffmpeg extraction helpers for the video-import pipeline (VID-01).

Audio extraction only in this slice — the audio spine drives Stage 1
("Audio is the spine", CLAUDE.md). Frame extraction lands with the masking
slice (VID-04).

We shell out to the ``ffmpeg`` binary (bundled in the backend image) via
``asyncio.create_subprocess_exec`` rather than taking a Python ffmpeg
wrapper dependency — fewer moving parts, no GPL-linking surface. Argument
vectors are passed as a list (never a shell string) so a filename can never
be interpreted as a shell token.

PHI-safety: ffmpeg stderr can echo the input path; we never log it verbatim,
only a bounded ``ffmpeg_exit_{code}`` reason.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.modules.video_import.errors import VideoExtractionError

logger = logging.getLogger("aurion.video_import.extraction")

# Whisper-friendly audio shape: 16 kHz mono signed-16-bit PCM WAV. Matches
# what the transcription providers expect; mono + 16 kHz keeps the upload
# small without hurting ASR quality.
_AUDIO_SAMPLE_RATE = 16000
_AUDIO_CHANNELS = 1

# Cap how long a single ffmpeg invocation may run so a malformed upload
# cannot wedge a worker indefinitely. Generous for a long encounter.
_FFMPEG_TIMEOUT_SECONDS = 600


async def extract_audio(video_path: str, out_wav_path: str) -> str:
    """Extract the audio track of ``video_path`` to a 16 kHz mono WAV.

    Args:
        video_path: Path to the source video on local (ECS task) disk.
        out_wav_path: Destination path for the extracted WAV.

    Returns:
        ``out_wav_path`` on success.

    Raises:
        VideoExtractionError: ffmpeg exited non-zero (e.g. the input has no
            audio stream or is not a media file), timed out, or produced an
            empty file. ``reason`` is a bounded, PHI-free string.
    """
    args = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        video_path,
        "-vn",  # drop video — audio only
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(_AUDIO_SAMPLE_RATE),
        "-ac",
        str(_AUDIO_CHANNELS),
        out_wav_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        # ffmpeg binary missing from the image — a deploy/config error.
        raise VideoExtractionError("ffmpeg_not_installed") from exc

    try:
        # communicate() drains stderr (PIPE) so the child can't deadlock on a
        # full pipe buffer; we deliberately discard the captured bytes — they
        # echo the input path and must never be logged.
        await asyncio.wait_for(
            proc.communicate(), timeout=_FFMPEG_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise VideoExtractionError("ffmpeg_timeout") from exc

    if proc.returncode != 0:
        # Never log stderr verbatim (it echoes the input path). The exit
        # code is the only signal we surface.
        logger.warning("ffmpeg audio extraction failed: exit=%s", proc.returncode)
        raise VideoExtractionError(f"ffmpeg_exit_{proc.returncode}")

    if not os.path.exists(out_wav_path) or os.path.getsize(out_wav_path) == 0:
        raise VideoExtractionError("empty_audio_output")

    logger.info("Audio extracted: bytes=%d", os.path.getsize(out_wav_path))
    return out_wav_path
