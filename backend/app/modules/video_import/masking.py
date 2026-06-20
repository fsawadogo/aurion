"""Server-side frame masking for the video-import pipeline (VID-04).

The compliance-critical trust-boundary step: the SERVER (not iOS) blurs every
detected face before a frame is stored or shown to a vision provider.

Design choices that keep the boundary safe:
  * **Detection is local + in-process** — OpenCV's bundled Haar cascade
    (`cv2.data.haarcascades`). Unmasked frames NEVER leave the task (no managed
    CV API). The `mask_frame` signature lets a stronger detector (DNN /
    MediaPipe) drop in later without touching callers.
  * **Fail-closed** — any decode / detect / blur / encode error drops the frame
    (`status="failed"`, no bytes). The ONLY path that returns image bytes is the
    all-faces-blurred success path (or an explicit keep-zero-face when the
    operator opts in). No path ever returns the original, unmasked frame.

Gated by `feature_flags.video_import_enabled` (off) — and enabling it in a PHI
environment additionally requires compliance sign-off.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

import cv2
import numpy as np

logger = logging.getLogger("aurion.video_import.masking")

# Lazily-built singleton — loading the cascade XML on every frame is wasteful.
_FACE_CASCADE: Optional["cv2.CascadeClassifier"] = None

# Blur strength floor. A kernel scaled to the face size makes features
# unrecoverable; this floor guards tiny detections.
_MIN_BLUR_KERNEL = 31
# Expand each detected bbox by this fraction on every side before blurring, so
# hairline/jaw/ear pixels outside the tight box are also covered.
_BBOX_MARGIN = 0.25


@dataclass
class MaskedFrameResult:
    """Outcome of masking one extracted frame.

    ``image_bytes`` is populated ONLY on ``status == "success"`` (the masked
    JPEG). On failure the frame is dropped and never stored. ``reason`` is a
    bounded, PHI-free string. ``faces_detected`` / ``faces_blurred`` feed the
    server-issued masking proof + audit counts.
    """

    status: Literal["success", "failed"]
    image_bytes: Optional[bytes] = None
    faces_detected: int = 0
    faces_blurred: int = 0
    reason: Optional[str] = None


def _cascade() -> "cv2.CascadeClassifier":
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _FACE_CASCADE = cv2.CascadeClassifier(path)
    return _FACE_CASCADE


def _fail(reason: str) -> MaskedFrameResult:
    return MaskedFrameResult(status="failed", image_bytes=None, reason=reason)


def _odd(n: int) -> int:
    return n if n % 2 == 1 else n + 1


def mask_frame(jpg_bytes: bytes, *, drop_zero_face: bool = True) -> MaskedFrameResult:
    """Blur every detected face in ``jpg_bytes`` and return the masked JPEG.

    Fail-closed: returns ``failed`` (drop the frame, never store the original)
    on any decode/detect/blur/encode error. ``faces_blurred`` always equals
    ``faces_detected`` on success.

    Args:
        jpg_bytes: Raw JPEG bytes of one extracted frame.
        drop_zero_face: When True (default) a frame with no detected face is
            dropped (conservative — a missed face must not be stored). When
            False the frame is kept (re-encoded, no blur) for face-free
            clinical content once detector recall is validated.
    """
    # 1. Decode.
    try:
        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001 — any decode failure drops the frame
        return _fail("decode_error")
    if img is None or img.size == 0:
        return _fail("decode_error")

    # 2. Detect faces (local, in-process).
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = _cascade()
        if cascade.empty():
            return _fail("cascade_load_error")
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
        )
    except Exception:  # noqa: BLE001 — detector error → fail closed
        return _fail("detect_error")

    n = len(faces)
    if n == 0:
        if drop_zero_face:
            return _fail("no_face_detected")
        ok, buf = cv2.imencode(".jpg", img)
        if not ok:
            return _fail("encode_error")
        return MaskedFrameResult(
            status="success", image_bytes=buf.tobytes(),
            faces_detected=0, faces_blurred=0,
        )

    # 3. Blur each detected face. Any failure here fails the WHOLE frame —
    #    a partially-blurred frame must never be stored.
    h, w = img.shape[:2]
    blurred = 0
    try:
        for (fx, fy, fw, fh) in faces:
            mx, my = int(fw * _BBOX_MARGIN), int(fh * _BBOX_MARGIN)
            x0, y0 = max(fx - mx, 0), max(fy - my, 0)
            x1, y1 = min(fx + fw + mx, w), min(fy + fh + my, h)
            roi = img[y0:y1, x0:x1]
            if roi.size == 0:
                return _fail("empty_roi")
            k = _odd(max(_MIN_BLUR_KERNEL, fw // 2))
            img[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)
            blurred += 1
    except Exception:  # noqa: BLE001 — blur error → fail closed
        return _fail("blur_error")

    if blurred != n:
        return _fail("incomplete_blur")

    # 4. Re-encode.
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        return _fail("encode_error")
    return MaskedFrameResult(
        status="success", image_bytes=buf.tobytes(),
        faces_detected=n, faces_blurred=blurred,
    )
