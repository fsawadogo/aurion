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
import tempfile

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


async def _run_ffmpeg(args: list[str]) -> None:
    """Run one ffmpeg invocation, fail-loud with a bounded PHI-free reason.

    Single source of truth for every ffmpeg shell-out (audio + frame
    extraction). Args are a list (never a shell string) so a filename can't be
    interpreted as a shell token; stderr is drained but never logged (it echoes
    the input path).

    Raises:
        VideoExtractionError: ``ffmpeg_not_installed`` / ``ffmpeg_timeout`` /
            ``ffmpeg_exit_{code}``.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VideoExtractionError("ffmpeg_not_installed") from exc

    try:
        await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise VideoExtractionError("ffmpeg_timeout") from exc

    if proc.returncode != 0:
        logger.warning("ffmpeg failed: exit=%s", proc.returncode)
        raise VideoExtractionError(f"ffmpeg_exit_{proc.returncode}")


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
    await _run_ffmpeg(
        [
            "ffmpeg", "-nostdin", "-y",
            "-i", video_path,
            "-vn",  # drop video — audio only
            "-acodec", "pcm_s16le",
            "-ar", str(_AUDIO_SAMPLE_RATE),
            "-ac", str(_AUDIO_CHANNELS),
            out_wav_path,
        ]
    )

    if not os.path.exists(out_wav_path) or os.path.getsize(out_wav_path) == 0:
        raise VideoExtractionError("empty_audio_output")

    logger.info("Audio extracted: bytes=%d", os.path.getsize(out_wav_path))
    return out_wav_path


# WAV header is a fixed 44 bytes for the canonical PCM layout extract_audio
# writes; the rest is raw samples at the known rate/width.
_WAV_HEADER_BYTES = 44


def wav_duration_ms(wav_path: str) -> int:
    """Duration of a 16 kHz mono signed-16-bit WAV, derived from file size.

    Avoids an ffprobe shell-out: bytes are PCM samples at a known rate/width,
    so duration = sample_bytes / (rate * channels * 2). Used to offset each
    clip's frame-trigger windows onto the merged (concatenated) timeline.
    """
    try:
        size = os.path.getsize(wav_path)
    except OSError:
        return 0
    sample_bytes = max(0, size - _WAV_HEADER_BYTES)
    bytes_per_ms = (_AUDIO_SAMPLE_RATE * _AUDIO_CHANNELS * 2) / 1000.0
    if bytes_per_ms <= 0:
        return 0
    return int(sample_bytes / bytes_per_ms)


async def concat_audio(wav_paths: list[str], out_wav_path: str) -> str:
    """Concatenate WAV clips (in the given order) into one 16 kHz mono WAV.

    Used for multi-clip imports: each clip's audio is extracted, then stitched
    end-to-end here into a single continuous timeline that is transcribed once.
    Re-encodes (not stream-copy) so mismatched headers across clips can't
    corrupt the output. A single path is returned as-is for that clip.

    Raises:
        VideoExtractionError: ffmpeg failed / produced an empty file.
    """
    if not wav_paths:
        raise VideoExtractionError("no_audio_to_concat")
    if len(wav_paths) == 1:
        return wav_paths[0]

    # ffmpeg concat demuxer reads a list file of `file '<path>'` lines.
    out_dir = os.path.dirname(out_wav_path) or "."
    list_path = os.path.join(out_dir, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        for p in wav_paths:
            # Single-quote-escape per the concat demuxer's quoting rules.
            escaped = p.replace("'", "'\\''")
            fh.write(f"file '{escaped}'\n")

    await _run_ffmpeg(
        [
            "ffmpeg", "-nostdin", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-acodec", "pcm_s16le",
            "-ar", str(_AUDIO_SAMPLE_RATE),
            "-ac", str(_AUDIO_CHANNELS),
            out_wav_path,
        ]
    )
    if not os.path.exists(out_wav_path) or os.path.getsize(out_wav_path) == 0:
        raise VideoExtractionError("empty_concat_output")
    logger.info(
        "Audio concatenated: clips=%d bytes=%d",
        len(wav_paths),
        os.path.getsize(out_wav_path),
    )
    return out_wav_path


async def extract_frame_at_ms(video_path: str, timestamp_ms: int) -> bytes:
    """Extract a single JPEG frame from ``video_path`` at ``timestamp_ms``.

    Seeks with ``-ss`` (input-side, fast) and grabs one frame. Returns the
    raw JPEG bytes.

    Raises:
        VideoExtractionError: ffmpeg exited non-zero / produced no frame
            (e.g. the timestamp is past the end of the video). Bounded,
            PHI-free reason.
    """
    seconds = max(timestamp_ms, 0) / 1000.0
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "frame.jpg")
        await _run_ffmpeg(
            [
                "ffmpeg", "-nostdin", "-y",
                "-ss", f"{seconds:.3f}",
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "3",
                out_path,
            ]
        )
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise VideoExtractionError("empty_frame_output")
        with open(out_path, "rb") as fh:
            return fh.read()


async def extract_frames_at_windows(
    video_path: str,
    windows: list[tuple[int, int]],
    fps: int,
) -> list[tuple[int, bytes]]:
    """Sample frames from ``video_path`` inside each ``(start_ms, end_ms)``
    window at ``fps``.

    Returns ``[(timestamp_ms, jpg_bytes)]`` (deduplicated + sorted by
    timestamp). A window always yields at least one sample (its midpoint),
    so a zero-length or sub-frame-interval window still contributes a frame.
    A frame that fails to extract (e.g. past EOF) is skipped, not fatal —
    one bad timestamp must not sink the whole import.
    """
    fps = max(fps, 1)
    step_ms = max(int(1000 / fps), 1)

    timestamps: list[int] = []
    for start_ms, end_ms in windows:
        lo, hi = (start_ms, end_ms) if start_ms <= end_ms else (end_ms, start_ms)
        if hi - lo < step_ms:
            timestamps.append((lo + hi) // 2)
            continue
        t = lo
        while t <= hi:
            timestamps.append(t)
            t += step_ms

    seen: set[int] = set()
    out: list[tuple[int, bytes]] = []
    for ts in sorted(timestamps):
        if ts in seen:
            continue
        seen.add(ts)
        try:
            jpg = await extract_frame_at_ms(video_path, ts)
        except VideoExtractionError:
            logger.info("Skipping unextractable frame at ts=%dms", ts)
            continue
        out.append((ts, jpg))
    return out
