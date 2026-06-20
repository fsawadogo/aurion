"""Server-side frame masking for the video-import pipeline.

VID-03 ships the **stub**: `mask_frame` always FAILS (drops the frame), so no
patient face is ever stored server-side while the wiring is validated — the
import degrades to frames-absent, identical to an audio-only session.

VID-04 replaces the stub body with real OpenCV face detection + Gaussian blur
behind the SAME signature (fail-closed: a frame is stored only when every
detected face was blurred). The compliance-critical trust-boundary change is
isolated to that slice; the orchestrator + result contract here do not change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger("aurion.video_import.masking")


@dataclass
class MaskedFrameResult:
    """Outcome of masking one extracted frame.

    ``image_bytes`` is populated ONLY on ``status == "success"`` (the masked
    JPEG). On failure the frame is dropped and never stored. ``reason`` is a
    bounded, PHI-free string. ``faces_detected`` / ``faces_blurred`` feed the
    server-issued masking proof + audit counts (VID-04).
    """

    status: Literal["success", "failed"]
    image_bytes: Optional[bytes] = None
    faces_detected: int = 0
    faces_blurred: int = 0
    reason: Optional[str] = None


def mask_frame(jpg_bytes: bytes) -> MaskedFrameResult:  # noqa: ARG001 — stub
    """VID-03 STUB — fail closed: drop every frame.

    Real face detection + blur lands in VID-04. Until then, returning
    ``failed`` guarantees the orchestrator stores zero frames, so no
    unmasked (or even masked) patient face reaches S3 or a vision provider
    while the feature is exercised.
    """
    return MaskedFrameResult(
        status="failed",
        image_bytes=None,
        reason="masking_not_implemented",
    )
