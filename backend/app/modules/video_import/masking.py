"""Server-side frame masking for the video-import pipeline (VID-04).

The compliance-critical trust-boundary step: the SERVER (not iOS) blurs every
detected face before a frame is stored or shown to a vision provider.

Design choices that keep the boundary safe:
  * **Detection is local + in-process** — OpenCV res10 SSD DNN when its weights
    are present (downloaded at Docker build time), falling back to the bundled
    Haar cascade otherwise (CI / local / failed download). Unmasked frames NEVER
    leave the task (no managed CV API). Detection is pluggable behind
    `_detect_faces`, so the model can change without touching `mask_frame`.
  * **Fail-closed** — any decode / detect / blur / encode error drops the frame
    (`status="failed"`, no bytes). The ONLY path that returns image bytes is the
    all-faces-blurred success path (or an explicit keep-zero-face when the
    operator opts in). No path ever returns the original, unmasked frame.

Gated by `feature_flags.video_import_enabled` (off) — and enabling it in a PHI
environment additionally requires compliance sign-off.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

import cv2
import numpy as np

logger = logging.getLogger("aurion.video_import.masking")

# Lazily-built singletons — loading a model on every frame is wasteful.
_FACE_CASCADE: Optional["cv2.CascadeClassifier"] = None
_DNN_NET: Optional["cv2.dnn.Net"] = None
_DNN_TRIED = False

# DNN face detector (VID-07). OpenCV's res10 SSD — higher recall than the Haar
# cascade, especially off-angle faces. Weights are downloaded into MODEL_DIR at
# Docker build time (best-effort); when absent (CI / local / failed download)
# detection falls back to the bundled Haar cascade. The detector is pluggable
# behind `_detect_faces` so a future model swap needs no caller change.
_MODEL_DIR = os.getenv("FACE_DETECTOR_MODEL_DIR", "/app/models")
_DNN_PROTO = "res10_deploy.prototxt"
_DNN_WEIGHTS = "res10.caffemodel"
_DNN_CONF = 0.5  # min detection confidence

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


def _dnn_net() -> Optional["cv2.dnn.Net"]:
    """Lazily load the res10 SSD net, or None if the weights aren't present.

    Tried at most once per process — a missing/corrupt model permanently
    falls back to Haar without re-probing the filesystem on every frame.
    """
    global _DNN_NET, _DNN_TRIED
    if _DNN_TRIED:
        return _DNN_NET
    _DNN_TRIED = True
    proto = os.path.join(_MODEL_DIR, _DNN_PROTO)
    weights = os.path.join(_MODEL_DIR, _DNN_WEIGHTS)
    if os.path.exists(proto) and os.path.exists(weights):
        try:
            _DNN_NET = cv2.dnn.readNetFromCaffe(proto, weights)
            logger.info("Face detector: DNN (res10 SSD) loaded from %s", _MODEL_DIR)
        except Exception:  # noqa: BLE001 — bad model → Haar fallback
            logger.warning("DNN face model failed to load; falling back to Haar")
            _DNN_NET = None
    else:
        logger.info("Face detector: DNN weights absent — using Haar cascade")
    return _DNN_NET


def _detect_faces(img: "np.ndarray") -> list[tuple[int, int, int, int]]:
    """Return face bounding boxes ``(x, y, w, h)`` using DNN when available,
    else the Haar cascade. Raises on a detector error (caller fails closed)."""
    net = _dnn_net()
    if net is not None:
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(
            cv2.resize(img, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0)
        )
        net.setInput(blob)
        det = net.forward()
        boxes: list[tuple[int, int, int, int]] = []
        for i in range(det.shape[2]):
            if float(det[0, 0, i, 2]) < _DNN_CONF:
                continue
            x1 = int(det[0, 0, i, 3] * w)
            y1 = int(det[0, 0, i, 4] * h)
            x2 = int(det[0, 0, i, 5] * w)
            y2 = int(det[0, 0, i, 6] * h)
            boxes.append((max(x1, 0), max(y1, 0), max(x2 - x1, 0), max(y2 - y1, 0)))
        return boxes

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = _cascade()
    if cascade.empty():
        raise RuntimeError("cascade_load_error")
    return [
        (int(x), int(y), int(w), int(h))
        for (x, y, w, h) in cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
        )
    ]


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

    # 2. Detect faces (local, in-process — DNN if available, else Haar).
    try:
        faces = _detect_faces(img)
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
