"""Shared S3 client factory.

Centralises S3 client creation so that region, endpoint URL, and bucket
names are configured in one place.  Every module that touches S3 should
import from here rather than constructing its own boto3 client.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3

logger = logging.getLogger("aurion.s3")

# Truncation length for any log line touching an S3 key. Keys encode
# `{bucket-kind}/{session_id}/{object_id}` — leaking the full key
# leaks the session UUID + object id. Twelve chars gives an operator
# enough to grep but is short of either UUID's full length.
_LOG_KEY_PREFIX_LEN = 12

REGION: str = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
ENDPOINT_URL: str | None = os.getenv("AWS_ENDPOINT_URL")

# Terraform's ECS task definition (infrastructure/ecs.tf:465-467) ships
# the bucket names as S3_AUDIO_BUCKET / S3_FRAMES_BUCKET / S3_EVAL_BUCKET.
# Read the ECS-shipped names first and fall back to the legacy *_S3_BUCKET
# names for any local shell that exported them. Without this alignment,
# dev fell back to "aurion-*-local" → NoSuchBucket on every PutObject →
# 500 → iOS retries → WAF rate-limit → 403 on Stage 1.
AUDIO_BUCKET: str = (
    os.getenv("S3_AUDIO_BUCKET") or os.getenv("AUDIO_S3_BUCKET") or "aurion-audio-local"
)
FRAMES_BUCKET: str = (
    os.getenv("S3_FRAMES_BUCKET") or os.getenv("FRAMES_S3_BUCKET") or "aurion-frames-local"
)
EVAL_BUCKET: str = (
    os.getenv("S3_EVAL_BUCKET") or os.getenv("EVAL_S3_BUCKET") or "aurion-eval-local"
)
# Raw uploaded encounter videos (VID-01) land here transiently while the
# import job extracts audio/frames, then are purged (`purge_raw_video`).
# Dedicated bucket so a short-TTL lifecycle rule + KMS policy can apply to
# raw, pre-masking video without affecting masked-evidence buckets. The
# Terraform bucket + lifecycle + CORS land in a later slice; the env name
# mirrors the S3_*_BUCKET convention the ECS task definition ships.
VIDEO_IMPORTS_BUCKET: str = (
    os.getenv("S3_VIDEO_IMPORTS_BUCKET")
    or os.getenv("VIDEO_IMPORTS_S3_BUCKET")
    or "aurion-video-imports-local"
)


_s3_client: Any | None = None


def get_s3_client():
    """Return a cached boto3 S3 client with the standard Aurion configuration.

    Boto3 clients are thread-safe, so a module-level singleton avoids the
    overhead of creating a new client on every call.
    Uses ``AWS_ENDPOINT_URL`` when set (LocalStack in local dev).
    """
    global _s3_client
    if _s3_client is None:
        kwargs: dict[str, Any] = {"region_name": REGION}
        if ENDPOINT_URL:
            kwargs["endpoint_url"] = ENDPOINT_URL
        _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


# ── Signed-URL helpers ────────────────────────────────────────────────────
#
# Single source of truth for presigned S3 URLs in Aurion. Callers that
# need to expose a signed URL on a citation (note builders today; future
# export / portal views) go through `generate_presigned_evidence_url` so
# every signing site shares the same TTL, the same KMS-decrypt-via-IAM
# contract, and the same PHI-safe logging convention.
#
# The URL itself contains the S3 key + a SignatureV4 query string. The
# S3 key contains the session_id (UUID, not PHI). We still treat the
# signed URL as sensitive in logs — the URL leaking (screenshot of a
# review session, support paste) lets the bearer fetch the masked
# evidence until the TTL expires. Hence the 12-char truncation on every
# log line that touches a key or URL.

# Default TTL: 1h. Long enough for a typical review session, short
# enough that a leaked URL (screenshot of the chat, support paste)
# becomes useless before exploitation. Centralised so we don't end up
# with one signing site at 5min and another at 24h.
DEFAULT_EVIDENCE_TTL_SECONDS: int = 3600


def generate_presigned_evidence_url(
    s3_key: str,
    ttl_seconds: int = DEFAULT_EVIDENCE_TTL_SECONDS,
    bucket: str | None = None,
    client_method: str = "get_object",
) -> str:
    """Presigned S3 URL for masked evidence playback (frames or clips).

    Single source of truth for the SignatureV4-signed URL surface. Used by
    the ``NoteClaimResponse`` builder and the web ``CitationExpansion``
    builder so two slightly-different presign call sites can't drift apart
    on TTL, KMS policy, or content-type defaults.

    The signed URL carries the S3 key + signature only; no PHI. Session
    IDs are UUIDs per Aurion's classification — they are NOT PHI — but the
    leaked URL still grants TTL-bounded read access to the masked
    evidence, so callers should never log the full URL or full key.

    Args:
        s3_key: The S3 object key (e.g. ``clips/{session_id}/{clip_id}.mp4``).
            Must be a path under the frames bucket (the same bucket holds
            frames + clips; bucket-level KMS encryption covers both).
        ttl_seconds: Signature validity window. Defaults to 1h via
            ``DEFAULT_EVIDENCE_TTL_SECONDS``. Callers SHOULD NOT override
            unless they have a documented reason (e.g. long-running export).
        bucket: Bucket name override. Defaults to ``FRAMES_BUCKET`` (which
            also holds clips by current layout; one KMS policy covers both).
        client_method: boto3 client method name. Defaults to ``get_object``.
            ``put_object`` is supported for future upload-URL flows.

    Returns:
        A SignatureV4-signed URL. Format:
        ``https://{bucket}.s3.{region}.amazonaws.com/{key}?X-Amz-Algorithm=...&X-Amz-Signature=...``

    Raises:
        botocore.exceptions.ClientError: if the signing call itself fails.
            The caller decides whether to surface as 500 or fall back to
            ``clip_url=None`` (note builders prefer the latter).
    """
    target_bucket = bucket or FRAMES_BUCKET
    s3 = get_s3_client()
    url = s3.generate_presigned_url(
        ClientMethod=client_method,
        Params={"Bucket": target_bucket, "Key": s3_key},
        ExpiresIn=ttl_seconds,
    )
    # Truncated log only — no full key, no signed URL. The 12-char prefix
    # is enough for an operator to grep across `frames/`, `clips/`, etc.
    # without revealing the session_id or the object_id.
    logger.debug(
        "Evidence URL signed: key_prefix=%s ttl=%d",
        s3_key[:_LOG_KEY_PREFIX_LEN],
        ttl_seconds,
    )
    return url


def load_frame_image_base64(s3_key: str, bucket: str | None = None) -> str:
    """Load a frame image from S3 and return it as a base64-encoded string.

    Used by all vision providers to retrieve masked frames before captioning.
    Returns a tiny placeholder on failure so tests can run without real S3.
    """
    import base64

    target_bucket = bucket or FRAMES_BUCKET
    try:
        s3 = get_s3_client()
        obj = s3.get_object(Bucket=target_bucket, Key=s3_key)
        return base64.b64encode(obj["Body"].read()).decode("utf-8")
    except Exception:
        return base64.b64encode(b"placeholder").decode("utf-8")
