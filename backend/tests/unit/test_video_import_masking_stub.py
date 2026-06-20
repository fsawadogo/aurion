"""VID-03 — the masking STUB must fail closed for every input.

Until VID-04 lands real OpenCV masking, `mask_frame` must NEVER return a
storable image — so the orchestrator stores zero frames and no patient face
reaches S3 while the frame path is exercised.
"""

from __future__ import annotations

from app.modules.video_import.masking import MaskedFrameResult, mask_frame


def test_stub_drops_every_frame() -> None:
    result = mask_frame(b"\xff\xd8\xff\xe0 jpeg-ish bytes")
    assert isinstance(result, MaskedFrameResult)
    assert result.status == "failed"
    assert result.image_bytes is None
    assert result.faces_blurred == 0


def test_stub_drops_empty_input_too() -> None:
    assert mask_frame(b"").status == "failed"
    assert mask_frame(b"").image_bytes is None
