"""P0-02: masking proof contract on frame upload.

Validates the `MaskingProof` model enforces the on-device masking contract:
- frame_type must be 'video' or 'screen'
- masking_status must be 'success' (failed/skipped frames must never reach
  this endpoint — iOS fail-closes per P0-01)
- counts must be non-negative integers
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.types import MaskingProof


class TestMaskingProofValid:
    def test_valid_video_proof(self):
        proof = MaskingProof(
            frame_type="video",
            masking_status="success",
            faces_detected=2,
            phi_regions_redacted=0,
        )
        assert proof.frame_type == "video"
        assert proof.faces_detected == 2

    def test_valid_screen_proof(self):
        proof = MaskingProof(
            frame_type="screen",
            masking_status="success",
            faces_detected=0,
            phi_regions_redacted=4,
        )
        assert proof.frame_type == "screen"
        assert proof.phi_regions_redacted == 4

    def test_zero_counts_allowed(self):
        # A clean frame (no faces, no PHI) is still a valid successful
        # masking pass — the pipeline ran, just had nothing to redact.
        proof = MaskingProof(
            frame_type="video",
            masking_status="success",
            faces_detected=0,
            phi_regions_redacted=0,
        )
        assert proof.faces_detected == 0


class TestMaskingProofRejects:
    def test_rejects_unknown_frame_type(self):
        with pytest.raises(ValidationError):
            MaskingProof(
                frame_type="thermal",
                masking_status="success",
                faces_detected=0,
                phi_regions_redacted=0,
            )

    def test_rejects_failed_masking_status(self):
        # P0-01 contract: failed masking must not reach this endpoint.
        with pytest.raises(ValidationError):
            MaskingProof(
                frame_type="video",
                masking_status="failed",
                faces_detected=0,
                phi_regions_redacted=0,
            )

    def test_rejects_skipped_masking_status(self):
        with pytest.raises(ValidationError):
            MaskingProof(
                frame_type="video",
                masking_status="skipped",
                faces_detected=0,
                phi_regions_redacted=0,
            )

    def test_rejects_negative_face_count(self):
        with pytest.raises(ValidationError):
            MaskingProof(
                frame_type="video",
                masking_status="success",
                faces_detected=-1,
                phi_regions_redacted=0,
            )

    def test_rejects_negative_phi_count(self):
        with pytest.raises(ValidationError):
            MaskingProof(
                frame_type="screen",
                masking_status="success",
                faces_detected=0,
                phi_regions_redacted=-3,
            )

    def test_rejects_missing_fields(self):
        with pytest.raises(ValidationError):
            MaskingProof(frame_type="video")  # type: ignore[call-arg]
