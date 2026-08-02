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

# EAST scene-text detector (standalone-visual secondary redaction). When a
# frame has ZERO detected faces the standalone-visual path KEEPS it (a knee /
# foot / wound close-up is clinically valuable and face-free) — but ONLY after
# blurring any on-screen text (a monitor / EMR could carry a name / MRN). The
# text detector is LOCAL + in-process (same trust-boundary invariant as the
# face detector — an unmasked frame never leaves the task, so no managed OCR).
# Weights are fetched into MODEL_DIR at Docker build (best-effort, like res10).
# FAIL-CLOSED: if the model is absent or detection errors, the frame is DROPPED
# rather than stored un-scrubbed — so a deploy without the model degrades to
# today's drop behaviour, never to storing an unredacted frame.
_EAST_NET: Optional["cv2.dnn.Net"] = None
_EAST_TRIED = False
_EAST_WEIGHTS = "frozen_east_text_detection.pb"
_EAST_CONF = 0.5  # min text-region confidence
_EAST_NMS = 0.4
# EAST requires input dims that are multiples of 32.
_EAST_INPUT = 320
# Expand each detected text box by this fraction before blurring, so glyph
# edges just outside the tight box are also covered.
_TEXT_BBOX_MARGIN = 0.15

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
    server-issued masking proof + audit counts. ``text_regions_redacted`` is
    the count of on-screen text regions blurred by the secondary redaction pass
    (only non-zero on the keep-faceless path).
    """

    status: Literal["success", "failed"]
    image_bytes: Optional[bytes] = None
    faces_detected: int = 0
    faces_blurred: int = 0
    reason: Optional[str] = None
    text_regions_redacted: int = 0


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


def _east_net() -> Optional["cv2.dnn.Net"]:
    """Lazily load the EAST text detector, or None if its weights are absent.

    Tried at most once per process (a missing model must not re-probe the
    filesystem on every frame). Absence is NOT an error here — the caller
    (`_detect_text_regions`) turns a None net into a fail-closed drop.
    """
    global _EAST_NET, _EAST_TRIED
    if _EAST_TRIED:
        return _EAST_NET
    _EAST_TRIED = True
    weights = os.path.join(_MODEL_DIR, _EAST_WEIGHTS)
    if os.path.exists(weights):
        try:
            _EAST_NET = cv2.dnn.readNet(weights)
            logger.info("Text detector: EAST loaded from %s", _MODEL_DIR)
        except Exception:  # noqa: BLE001 — bad model → treated as absent
            logger.warning("EAST text model failed to load; text redaction off")
            _EAST_NET = None
    else:
        logger.info("Text detector: EAST weights absent — faceless frames drop")
    return _EAST_NET


def _detect_text_regions(img: "np.ndarray") -> list[tuple[int, int, int, int]]:
    """Return axis-aligned text bounding boxes ``(x, y, w, h)`` via EAST.

    Raises ``RuntimeError`` when the model is absent so the caller fails closed
    (drops the frame rather than storing it un-scrubbed). Any detector error
    also raises. The boxes are scaled back to the original image size.
    """
    net = _east_net()
    if net is None:
        raise RuntimeError("east_model_absent")
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(img, (_EAST_INPUT, _EAST_INPUT)),
        1.0,
        (_EAST_INPUT, _EAST_INPUT),
        (123.68, 116.78, 103.94),
        swapRB=True,
        crop=False,
    )
    net.setInput(blob)
    scores, geometry = net.forward(
        ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"]
    )
    rx, ry = w / float(_EAST_INPUT), h / float(_EAST_INPUT)
    rects: list[list[int]] = []
    confidences: list[float] = []
    n_rows, n_cols = scores.shape[2], scores.shape[3]
    for y in range(n_rows):
        scores_data = scores[0, 0, y]
        x0, x1, x2, x3 = (geometry[0, i, y] for i in range(4))
        angles = geometry[0, 4, y]
        for x in range(n_cols):
            score = float(scores_data[x])
            if score < _EAST_CONF:
                continue
            offset_x, offset_y = x * 4.0, y * 4.0
            angle = float(angles[x])
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            box_h = float(x0[x]) + float(x2[x])
            box_w = float(x1[x]) + float(x3[x])
            end_x = int(offset_x + cos_a * float(x1[x]) + sin_a * float(x2[x]))
            end_y = int(offset_y - sin_a * float(x1[x]) + cos_a * float(x2[x]))
            start_x = int(end_x - box_w)
            start_y = int(end_y - box_h)
            # Scale the (input-space) box back onto the original frame.
            rects.append(
                [
                    int(start_x * rx),
                    int(start_y * ry),
                    int((end_x - start_x) * rx),
                    int((end_y - start_y) * ry),
                ]
            )
            confidences.append(score)
    if not rects:
        return []
    keep = cv2.dnn.NMSBoxes(rects, confidences, _EAST_CONF, _EAST_NMS)
    if keep is None or len(keep) == 0:
        return []
    # NMSBoxes returns a 2-D array (older cv2), a 1-D array, or a list of ints
    # across versions — flatten uniformly so indexing never breaks.
    idxs = np.array(keep).flatten().tolist()
    return [tuple(rects[i]) for i in idxs]


def _redact_faceless_frame(img: "np.ndarray") -> MaskedFrameResult:
    """Blur every on-screen text region in a zero-face frame, then re-encode.

    The secondary redaction pass for the standalone-visual keep-faceless path.
    FAIL-CLOSED: if the text detector is unavailable or errors, the frame is
    DROPPED (never stored un-scrubbed). A frame with no detected text is kept
    (a clean body-part close-up), re-encoded so no original bytes flow through.
    """
    try:
        regions = _detect_text_regions(img)
    except Exception:  # noqa: BLE001 — no model / detector error → fail closed
        return _fail("text_redaction_unavailable")

    h, w = img.shape[:2]
    redacted = 0
    try:
        for (tx, ty, tw, th) in regions:
            if tw <= 0 or th <= 0:
                continue
            mx, my = int(tw * _TEXT_BBOX_MARGIN), int(th * _TEXT_BBOX_MARGIN)
            x0, y0 = max(tx - mx, 0), max(ty - my, 0)
            x1, y1 = min(tx + tw + mx, w), min(ty + th + my, h)
            roi = img[y0:y1, x0:x1]
            if roi.size == 0:
                continue
            k = _odd(max(_MIN_BLUR_KERNEL, tw // 2))
            img[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)
            redacted += 1
    except Exception:  # noqa: BLE001 — any blur error → fail closed
        return _fail("text_redaction_error")

    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        return _fail("encode_error")
    return MaskedFrameResult(
        status="success",
        image_bytes=buf.tobytes(),
        faces_detected=0,
        faces_blurred=0,
        text_regions_redacted=redacted,
    )


def _fail(reason: str) -> MaskedFrameResult:
    return MaskedFrameResult(status="failed", image_bytes=None, reason=reason)


def _odd(n: int) -> int:
    return n if n % 2 == 1 else n + 1


def mask_frame(
    jpg_bytes: bytes,
    *,
    drop_zero_face: bool = True,
    redact_faceless: bool = False,
) -> MaskedFrameResult:
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
        redact_faceless: Standalone-visual keep-faceless path. When True and a
            frame has ZERO detected faces, the frame is KEPT after a secondary
            text-region redaction pass (blur any on-screen text that could
            carry PHI), instead of being dropped. FAIL-CLOSED: if the text
            detector is unavailable the frame is dropped, not stored. Takes
            precedence over ``drop_zero_face`` in the zero-face branch. A frame
            WITH faces is unaffected (faces are blurred exactly as before).
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
        # Standalone-visual keep-faceless path takes precedence: KEEP the frame
        # but scrub any on-screen text first (fail-closed to drop if the text
        # detector is unavailable). This retains clinically-valuable face-free
        # close-ups (knee / foot / wound) without storing on-screen PHI.
        if redact_faceless:
            return _redact_faceless_frame(img)
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
