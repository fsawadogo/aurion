"""M-08 / B-05: screen-frame OCR results render as descriptive-mode
claims that the note pipeline can append directly. Only the pure helper
is unit-tested here — the DB merge path is exercised in integration.
"""

from __future__ import annotations

from app.api.v1.screen import _value_to_claim_text
from app.core.types import NoteClaim, ScreenLabValue


class TestValueToClaimText:
    def test_lab_value_with_unit(self):
        text = _value_to_claim_text(
            "lab_result",
            ScreenLabValue(name="Hemoglobin", value="138", unit="g/L"),
        )
        # Must be observational, not interpretive (CLAUDE.md §"Descriptive Mode")
        assert "138" in text
        assert "Hemoglobin" in text
        assert "g/L" in text
        assert "low" not in text.lower()
        assert "abnormal" not in text.lower()
        assert "diagnos" not in text.lower()

    def test_lab_value_without_unit(self):
        text = _value_to_claim_text(
            "lab_result",
            ScreenLabValue(name="WBC", value="9.2", unit=""),
        )
        assert "WBC" in text
        assert "9.2" in text
        assert text.strip().endswith("9.2")

    def test_imaging_metadata_renders_distinctly(self):
        text = _value_to_claim_text(
            "imaging_viewer",
            ScreenLabValue(name="modality", value="MRI", unit=""),
        )
        assert "Imaging metadata" in text
        assert "MRI" in text


class TestScreenClaimIsValid:
    def test_screen_source_type_passes_schema(self):
        # The Note model only accepts source_type in {"transcript", "visual", "screen"}.
        # If schema drift broke this, the merge would explode at runtime.
        claim = NoteClaim(
            id="screen_investigations_1",
            text="Screen-captured Hemoglobin: 138 g/L",
            source_type="screen",
            source_id="screen_18300",
            source_quote="Hemoglobin: 138 g/L",
        )
        assert claim.source_type == "screen"
        assert claim.source_id == "screen_18300"
