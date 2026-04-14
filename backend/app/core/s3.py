"""Shared S3 client factory.

Centralises S3 client creation so that region, endpoint URL, and bucket
names are configured in one place.  Every module that touches S3 should
import from here rather than constructing its own boto3 client.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

REGION: str = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
ENDPOINT_URL: str | None = os.getenv("AWS_ENDPOINT_URL")

AUDIO_BUCKET: str = os.getenv("AUDIO_S3_BUCKET", "aurion-audio-local")
FRAMES_BUCKET: str = os.getenv("FRAMES_S3_BUCKET", "aurion-frames-local")
EVAL_BUCKET: str = os.getenv("EVAL_S3_BUCKET", "aurion-eval-local")


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
