"""VID-04 — real server-side masking. Fail-closed is the load-bearing property.

No real face photo is needed: the fail-closed paths use invalid/empty/blank
input, and the blur-applied path monkeypatches the cascade to "detect" a rect
so we can assert the bbox is actually blurred + counts match — without ever
committing a face image to the repo.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.modules.video_import import masking
from app.modules.video_import.masking import MaskedFrameResult, mask_frame


def _solid_jpeg(color=(128, 128, 128), size=(120, 120)) -> bytes:
    img = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


# ── Fail-closed ────────────────────────────────────────────────────────────


def test_corrupt_bytes_fail_closed() -> None:
    r = mask_frame(b"not a jpeg at all")
    assert r.status == "failed" and r.image_bytes is None
    assert r.reason == "decode_error"


def test_empty_bytes_fail_closed() -> None:
    r = mask_frame(b"")
    assert r.status == "failed" and r.image_bytes is None


def test_detector_error_fails_closed(monkeypatch) -> None:
    class _Boom:
        def empty(self):
            return False

        def detectMultiScale(self, *_a, **_k):
            raise RuntimeError("detector exploded")

    monkeypatch.setattr(masking, "_cascade", lambda: _Boom())
    r = mask_frame(_solid_jpeg())
    assert r.status == "failed" and r.image_bytes is None
    assert r.reason == "detect_error"


def test_never_returns_original_bytes() -> None:
    """The original (unmasked) bytes must never be the returned image."""
    original = _solid_jpeg()
    r = mask_frame(original)  # blank image → no face → dropped by default
    assert r.image_bytes is None


# ── Zero-face policy ─────────────────────────────────────────────────────────


def test_zero_face_dropped_by_default() -> None:
    r = mask_frame(_solid_jpeg(), drop_zero_face=True)
    assert r.status == "failed"
    assert r.reason == "no_face_detected"


def test_zero_face_kept_when_opted_in() -> None:
    r = mask_frame(_solid_jpeg(), drop_zero_face=False)
    assert r.status == "success"
    assert r.image_bytes is not None
    assert r.faces_detected == 0 and r.faces_blurred == 0


# ── Blur-applied (cascade monkeypatched to "detect" a region) ───────────────


def test_detected_face_is_blurred(monkeypatch) -> None:
    # A noisy image so a blur measurably reduces local variance.
    rng = np.random.RandomState(0)
    img = rng.randint(0, 256, (120, 120, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    jpg = buf.tobytes()

    rect = (30, 30, 40, 40)  # x, y, w, h

    class _OneFace:
        def empty(self):
            return False

        def detectMultiScale(self, *_a, **_k):
            return np.array([rect])

    monkeypatch.setattr(masking, "_cascade", lambda: _OneFace())
    r = mask_frame(jpg, drop_zero_face=True)

    assert isinstance(r, MaskedFrameResult)
    assert r.status == "success"
    assert r.faces_detected == 1 and r.faces_blurred == 1
    assert r.image_bytes is not None

    # The blurred region's variance must drop vs the original.
    out = cv2.imdecode(np.frombuffer(r.image_bytes, np.uint8), cv2.IMREAD_COLOR)
    x, y, w, h = rect
    before = float(img[y : y + h, x : x + w].var())
    after = float(out[y : y + h, x : x + w].var())
    assert after < before
