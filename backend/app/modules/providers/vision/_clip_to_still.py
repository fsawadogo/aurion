"""Lossy clip-to-still extraction (P1-2).

Single source of truth for the midpoint-still fallback used by
frame-only vision providers (OpenAI, Anthropic today) to fulfil the
`caption_clip` contract. Native-video providers (Gemini) bypass this
helper entirely and send MP4 bytes to the model directly.

DRY (section 6c): if a third provider ever needs the same fallback
shape, it imports `extract_midpoint_still` -- it does NOT inline the
ffmpeg plumbing. The rule-of-three check is satisfied by extracting
now, because the alternative is two near-identical implementations in
`openai.py` and `anthropic.py` plus a guaranteed third copy when the
next non-video provider arrives.

The flow is:
1. Fetch MP4 bytes from S3 via the existing `get_s3_client()` helper
   (DIP -- no direct boto3 construction here).
2. Run the system `ffmpeg` binary as a subprocess using the safe
   `asyncio.create_subprocess_exec` API (argv list, no shell). Seek
   to the midpoint and emit one JPEG frame.
3. Upload the resulting JPEG back to S3 under a derived key so the
   provider's `caption_frame` path (which loads from S3) sees a real
   masked frame instead of a placeholder.
4. Return a synthetic `MaskedFrame` whose `timestamp_ms` is the clip
   midpoint and `s3_key` points at the extracted still. The
   `masking_confirmed=True` flag is propagated unchanged -- the clip
   was masked on-device before upload, so the still inherits that
   guarantee.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.core.types import MaskedClip, MaskedFrame

logger = logging.getLogger("aurion.providers.vision._clip_to_still")

# Truncated key length used in log lines so we never leak a full S3
# path (which could carry session-id segments traceable to a patient).
_LOG_KEY_PREFIX_LEN: Final[int] = 12


def _truncate_key(s3_key: str) -> str:
    """Return a short, non-PHI prefix of an S3 key for logging."""
    return s3_key[:_LOG_KEY_PREFIX_LEN]


async def extract_midpoint_still(
    clip: MaskedClip,
    *,
    bucket: str | None = None,
) -> MaskedFrame:
    """Extract the midpoint frame of a masked clip as a `MaskedFrame`.

    Used by OpenAI and Anthropic `caption_clip` implementations as a
    lossy fallback when the provider doesn't accept video natively.

    Uses `asyncio.create_subprocess_exec` with an argv list -- no
    shell interpolation, no command-injection surface.

    Raises:
        FileNotFoundError: the system `ffmpeg` binary isn't on PATH.
            The message includes the binary name so the operator can
            install it without diving into the codebase.
        RuntimeError: ffmpeg ran but produced no output (corrupt clip,
            invalid container, etc.). The message names the operation
            but NOT the S3 key (PHI guard).
    """
    target_bucket = bucket or FRAMES_BUCKET
    s3 = get_s3_client()

    # 1. Pull the MP4 bytes from S3.
    obj = s3.get_object(Bucket=target_bucket, Key=clip.s3_key)
    mp4_bytes: bytes = obj["Body"].read()

    # 2. Spawn ffmpeg with an argv list (no shell), seek to midpoint,
    #    emit one JPEG. The argv form is the safe subprocess pattern.
    midpoint_seconds = (clip.duration_ms / 1000.0) / 2.0
    argv: list[str] = [
        "ffmpeg",
        "-loglevel", "error",
        "-y",
        "-ss", f"{midpoint_seconds:.3f}",
        "-i", "pipe:0",
        "-frames:v", "1",
        "-f", "image2",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        # Surface a clear, actionable error. The binary itself ships in
        # the runtime image; if a dev environment is missing it we say
        # so explicitly so the operator can install it.
        raise FileNotFoundError(
            "ffmpeg binary not found on PATH -- clip-to-still fallback "
            "requires the system `ffmpeg` binary to be installed."
        ) from exc

    stdout_bytes, stderr_bytes = await proc.communicate(input=mp4_bytes)
    if proc.returncode != 0 or not stdout_bytes:
        # Don't include the S3 key in the message -- that's a PHI guard.
        # ffmpeg's stderr is structured ("Invalid data found..."), not
        # patient-identifying, so the first line is safe for debugging.
        first_line = stderr_bytes.decode("utf-8", errors="replace").splitlines()[:1]
        detail = first_line[0] if first_line else "no stderr"
        logger.warning(
            "ffmpeg midpoint extract failed for clip %s (returncode=%s)",
            _truncate_key(clip.s3_key),
            proc.returncode,
        )
        raise RuntimeError(
            f"ffmpeg midpoint extraction produced no output: {detail}"
        )

    jpeg_bytes: bytes = stdout_bytes

    # 3. Upload the still under a derived key so `caption_frame` (which
    #    loads from S3) sees a real masked frame body. The derived key
    #    reuses the clip's prefix tree so the bucket TTL policy applies
    #    uniformly to both bodies and the audit observer can trace the
    #    still back to its parent clip.
    still_key = _derive_still_key(clip.s3_key)
    s3.put_object(
        Bucket=target_bucket,
        Key=still_key,
        Body=jpeg_bytes,
        ContentType="image/jpeg",
    )

    # 4. Synthesise a MaskedFrame at the clip midpoint.
    midpoint_ms = clip.timestamp_ms + clip.duration_ms // 2
    frame_id = f"{clip.trigger_segment_id}_midstill"

    logger.info(
        "extracted midpoint still for clip %s -> frame %s",
        _truncate_key(clip.s3_key),
        frame_id,
    )

    return MaskedFrame(
        frame_id=frame_id,
        session_id=session_id_from_clip_key(clip.s3_key),
        timestamp_ms=midpoint_ms,
        s3_key=still_key,
        masking_confirmed=True,
    )


def _derive_still_key(clip_s3_key: str) -> str:
    """Derive the S3 key for the extracted still from the clip key.

    Keeps the prefix tree intact so the bucket TTL policy applies
    uniformly to both bodies. `clips/{sess}/{trigger}.mp4` becomes
    `clips/{sess}/{trigger}.midstill.jpg`. Any leading `clips/`
    prefix is preserved; no leading directory is fabricated.
    """
    if clip_s3_key.lower().endswith(".mp4"):
        return clip_s3_key[:-4] + ".midstill.jpg"
    return clip_s3_key + ".midstill.jpg"


def session_id_from_clip_key(clip_s3_key: str) -> str:
    """Best-effort session-id extraction from a clip S3 key.

    Clip keys follow `clips/{session_id}/{trigger}.mp4`. The synthetic
    `MaskedFrame.session_id` is used downstream for citation linking;
    if the key shape ever drifts, we fall back to an empty string and
    let the upstream caller fill it from `clip` context -- the providers
    already have the session_id available via the anchor.

    Public helper so Gemini's native clip path (which doesn't extract a
    still) can share the same key-parsing logic. DRY (section 6c):
    one parser, used by both the still-fallback and the native path.
    """
    parts = clip_s3_key.split("/")
    if len(parts) >= 3 and parts[0] == "clips":
        return parts[1]
    return ""


# Backwards-compat alias for the private name used internally above.
_session_id_from_clip_key = session_id_from_clip_key
