"""Tests for screen capture pipeline — classification, extraction, routing, PHI redaction."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.types import ScreenCaptureResult, ScreenExtractedData, ScreenLabValue
from app.modules.screen.service import (
    classify_screen_type,
    extract_imaging_metadata,
    extract_lab_values,
    process_screen_frame,
    redact_phi,
)


# ── Screen Type Classification ───────────────────────────────────────────────


class TestClassifyScreenType:
    def test_lab_result_detected(self):
        text = (
            "Lab Results - Complete Blood Count (CBC)\n"
            "Hemoglobin: 138 g/L (120-160)\n"
            "WBC: 9.2 10^9/L (4.0-11.0)\n"
            "Reference Range\n"
        )
        assert classify_screen_type(text) == "lab_result"

    def test_imaging_viewer_detected(self):
        text = (
            "DICOM Viewer\n"
            "Modality: MRI\n"
            "Series: T2 Sagittal\n"
            "Laterality: Right\n"
        )
        assert classify_screen_type(text) == "imaging_viewer"

    def test_emr_detected(self):
        text = (
            "Electronic Medical Record\n"
            "Patient Chart - Encounter #12345\n"
            "Progress Note\n"
            "Medication List\n"
        )
        assert classify_screen_type(text) == "emr"

    def test_other_when_no_keywords_match(self):
        text = "This is just a random desktop screenshot with no clinical content."
        assert classify_screen_type(text) == "other"

    def test_other_when_below_threshold(self):
        # Only one keyword match — below the minimum threshold of 2
        text = "Some text mentioning hemoglobin but nothing else clinical."
        assert classify_screen_type(text) == "other"

    def test_lab_wins_over_imaging_when_more_keywords(self):
        text = (
            "Lab Results\n"
            "Hemoglobin: 138 g/L\n"
            "WBC: 9.2 10^9/L\n"
            "Platelet: 245 10^9/L\n"
            "Reference Range\n"
            "Series: 1\n"  # One imaging keyword
        )
        assert classify_screen_type(text) == "lab_result"

    def test_empty_text_returns_other(self):
        assert classify_screen_type("") == "other"


# ── Lab Value Extraction ─────────────────────────────────────────────────────


class TestExtractLabValues:
    def test_basic_lab_values(self):
        text = (
            "Hemoglobin: 138 g/L (120-160)\n"
            "WBC: 9.2 10^9/L (4.0-11.0)\n"
            "Platelet: 245 10^9/L (150-400)\n"
        )
        values = extract_lab_values(text)
        assert len(values) >= 2  # At least hemoglobin and WBC

        names = {v.name.lower() for v in values}
        assert "hemoglobin" in names

    def test_returns_screen_lab_value_type(self):
        text = "Hemoglobin: 138 g/L\n"
        values = extract_lab_values(text)
        assert all(isinstance(v, ScreenLabValue) for v in values)

    def test_value_and_unit_extracted(self):
        text = "Hemoglobin: 138 g/L\n"
        values = extract_lab_values(text)
        hgb = next((v for v in values if v.name.lower() == "hemoglobin"), None)
        assert hgb is not None
        assert hgb.value == "138"
        assert "g/L" in hgb.unit

    def test_ignores_non_lab_names(self):
        text = "RandomWord: 42 units\nHemoglobin: 138 g/L\n"
        values = extract_lab_values(text)
        names = {v.name.lower() for v in values}
        assert "randomword" not in names

    def test_empty_text_returns_empty(self):
        values = extract_lab_values("")
        assert values == []

    def test_no_duplicates(self):
        text = (
            "Hemoglobin: 138 g/L\n"
            "Hemoglobin: 140 g/L\n"
        )
        values = extract_lab_values(text)
        hgb_count = sum(1 for v in values if v.name.lower() == "hemoglobin")
        assert hgb_count == 1


# ── Imaging Metadata Extraction ──────────────────────────────────────────────


class TestExtractImagingMetadata:
    def test_modality_extracted(self):
        text = "Modality: MRI\nLaterality: Right\n"
        meta = extract_imaging_metadata(text)
        assert "modality" in meta
        assert "MRI" in meta["modality"]

    def test_laterality_extracted(self):
        text = "Laterality: Left\nModality: CT\n"
        meta = extract_imaging_metadata(text)
        assert "laterality" in meta
        assert meta["laterality"] == "Left"

    def test_series_label_extracted(self):
        text = "Series: T2 Sagittal\n"
        meta = extract_imaging_metadata(text)
        assert "series_label" in meta
        assert "T2 Sagittal" in meta["series_label"]

    def test_empty_text_returns_empty_dict(self):
        meta = extract_imaging_metadata("")
        assert meta == {}

    def test_metadata_only_no_image_content(self):
        text = "Modality: X-Ray\nLaterality: Right\nSeries: AP View\n"
        meta = extract_imaging_metadata(text)
        # Only modality, laterality, series_label keys allowed
        for key in meta:
            assert key in ("modality", "laterality", "series_label")


# ── PHI Redaction ────────────────────────────────────────────────────────────


class TestRedactPhi:
    def test_mrn_redacted(self):
        text = "MRN: 1234567890\nHemoglobin: 138 g/L"
        result = redact_phi(text)
        assert "1234567890" not in result
        assert "[REDACTED]" in result
        assert "Hemoglobin" in result  # Clinical data preserved

    def test_dob_redacted(self):
        text = "DOB: 1985-03-15\nWBC: 9.2"
        result = redact_phi(text)
        assert "1985-03-15" not in result
        assert "[REDACTED]" in result

    def test_dob_various_formats_redacted(self):
        text = "Date of Birth: 03/15/1985\nSome data"
        result = redact_phi(text)
        assert "03/15/1985" not in result
        assert "[REDACTED]" in result

    def test_health_card_redacted(self):
        text = "RAMQ: 1234 5678 9012\nLab result"
        result = redact_phi(text)
        assert "1234 5678 9012" not in result
        assert "[REDACTED]" in result

    def test_patient_name_redacted(self):
        text = "Patient Name: John Smith\nHemoglobin: 138"
        result = redact_phi(text)
        assert "John Smith" not in result
        assert "[REDACTED]" in result

    def test_ssn_sin_pattern_redacted(self):
        text = "SSN 123-45-6789\nSome data"
        result = redact_phi(text)
        assert "123-45-6789" not in result
        assert "[REDACTED]" in result

    def test_clinical_data_preserved(self):
        text = "Hemoglobin: 138 g/L\nWBC: 9.2 10^9/L"
        result = redact_phi(text)
        assert result == text  # No PHI, nothing changed

    def test_multiple_phi_types_redacted(self):
        text = (
            "Patient Name: Jane Doe\n"
            "MRN: 9876543\n"
            "DOB: 1990-01-01\n"
            "Hemoglobin: 138 g/L\n"
        )
        result = redact_phi(text)
        assert "Jane Doe" not in result
        assert "9876543" not in result
        assert "1990-01-01" not in result
        assert "Hemoglobin" in result

    def test_empty_text_unchanged(self):
        assert redact_phi("") == ""


# ── Full Pipeline — process_screen_frame ─────────────────────────────────────


class TestProcessScreenFrame:
    """Integration tests for the full screen capture pipeline.

    Uses mocked AppConfig and OCR to test end-to-end routing logic.
    """

    @pytest.fixture
    def mock_config_enabled(self):
        """Mock AppConfig with screen_capture_enabled=True."""
        mock_cfg = type("MockConfig", (), {
            "feature_flags": type("MockFlags", (), {
                "screen_capture_enabled": True,
            })(),
        })()
        with patch("app.modules.screen.service.get_config", return_value=mock_cfg):
            yield

    @pytest.fixture
    def mock_config_disabled(self):
        """Mock AppConfig with screen_capture_enabled=False."""
        mock_cfg = type("MockConfig", (), {
            "feature_flags": type("MockFlags", (), {
                "screen_capture_enabled": False,
            })(),
        })()
        with patch("app.modules.screen.service.get_config", return_value=mock_cfg):
            yield

    @pytest.mark.asyncio
    async def test_lab_frame_returns_structured_values(self, mock_config_enabled):
        lab_text = (
            "Lab Results - Complete Blood Count (CBC)\n"
            "Reference Range\n"
            "Hemoglobin: 138 g/L (120-160)\n"
            "WBC: 9.2 10^9/L (4.0-11.0)\n"
        )
        with patch(
            "app.modules.screen.service.extract_text_ocr",
            new_callable=AsyncMock,
            return_value=lab_text,
        ):
            result = await process_screen_frame(
                frame_id="screen_00089",
                session_id="test-session",
                timestamp_ms=18300,
                image_bytes=b"fake-image",
            )

        assert result is not None
        assert result.screen_type == "lab_result"
        assert result.integration_status == "injected"
        assert result.note_section_target == "investigations"
        assert result.extracted_data is not None
        assert result.extracted_data.type == "lab_values"
        assert len(result.extracted_data.values) >= 1
        assert isinstance(result, ScreenCaptureResult)

    @pytest.mark.asyncio
    async def test_imaging_frame_returns_metadata_only(self, mock_config_enabled):
        imaging_text = (
            "DICOM Viewer - Radiology\n"
            "Modality: MRI\n"
            "Laterality: Right\n"
            "Series: T2 Sagittal\n"
        )
        with patch(
            "app.modules.screen.service.extract_text_ocr",
            new_callable=AsyncMock,
            return_value=imaging_text,
        ):
            result = await process_screen_frame(
                frame_id="screen_00090",
                session_id="test-session",
                timestamp_ms=19000,
                image_bytes=b"fake-image",
            )

        assert result is not None
        assert result.screen_type == "imaging_viewer"
        assert result.integration_status == "injected"
        assert result.note_section_target == "imaging_review"
        assert result.extracted_data is not None
        assert result.extracted_data.type == "imaging_metadata"
        # Only metadata values — modality, laterality, series_label
        value_names = {v.name for v in result.extracted_data.values}
        allowed_keys = {"modality", "laterality", "series_label"}
        assert value_names.issubset(allowed_keys)

    @pytest.mark.asyncio
    async def test_emr_frame_skipped_not_injected(self, mock_config_enabled):
        emr_text = (
            "Electronic Medical Record\n"
            "Patient Chart - Encounter #12345\n"
            "Progress Note\n"
            "Medication List\n"
        )
        with patch(
            "app.modules.screen.service.extract_text_ocr",
            new_callable=AsyncMock,
            return_value=emr_text,
        ):
            result = await process_screen_frame(
                frame_id="screen_00091",
                session_id="test-session",
                timestamp_ms=20000,
                image_bytes=b"fake-image",
            )

        assert result is not None
        assert result.screen_type == "emr"
        assert result.integration_status == "skipped"
        assert result.note_section_target is None
        assert result.extracted_data is None

    @pytest.mark.asyncio
    async def test_other_frame_discarded(self, mock_config_enabled):
        other_text = "Just a random screenshot with no clinical content."
        with patch(
            "app.modules.screen.service.extract_text_ocr",
            new_callable=AsyncMock,
            return_value=other_text,
        ):
            result = await process_screen_frame(
                frame_id="screen_00092",
                session_id="test-session",
                timestamp_ms=21000,
                image_bytes=b"fake-image",
            )

        assert result is not None
        assert result.screen_type == "other"
        assert result.integration_status == "discarded"
        assert result.note_section_target is None
        assert result.extracted_data is None

    @pytest.mark.asyncio
    async def test_feature_flag_disabled_returns_none(self, mock_config_disabled):
        result = await process_screen_frame(
            frame_id="screen_00093",
            session_id="test-session",
            timestamp_ms=22000,
            image_bytes=b"fake-image",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_phi_redacted_before_processing(self, mock_config_enabled):
        phi_text = (
            "Lab Results - Complete Blood Count (CBC)\n"
            "Patient Name: John Smith\n"
            "MRN: 1234567890\n"
            "DOB: 1985-03-15\n"
            "Reference Range\n"
            "Hemoglobin: 138 g/L (120-160)\n"
            "WBC: 9.2 10^9/L (4.0-11.0)\n"
        )
        with patch(
            "app.modules.screen.service.extract_text_ocr",
            new_callable=AsyncMock,
            return_value=phi_text,
        ):
            result = await process_screen_frame(
                frame_id="screen_00094",
                session_id="test-session",
                timestamp_ms=23000,
                image_bytes=b"fake-image",
            )

        assert result is not None
        assert result.screen_type == "lab_result"
        # PHI should not appear in extracted data
        if result.extracted_data:
            for val in result.extracted_data.values:
                assert "John Smith" not in val.name
                assert "John Smith" not in val.value
                assert "1234567890" not in val.value
                assert "1985-03-15" not in val.value

    @pytest.mark.asyncio
    async def test_result_matches_output_schema(self, mock_config_enabled):
        """Verify the result matches the CLAUDE.md output schema contract."""
        lab_text = (
            "Lab Results - Complete Blood Count (CBC)\n"
            "Reference Range\n"
            "Hemoglobin: 138 g/L (120-160)\n"
            "WBC: 9.2 10^9/L (4.0-11.0)\n"
        )
        with patch(
            "app.modules.screen.service.extract_text_ocr",
            new_callable=AsyncMock,
            return_value=lab_text,
        ):
            result = await process_screen_frame(
                frame_id="screen_00089",
                session_id="test-uuid",
                timestamp_ms=18300,
                image_bytes=b"fake-image",
            )

        assert result is not None
        # All required fields present per schema
        assert result.frame_id == "screen_00089"
        assert result.session_id == "test-uuid"
        assert result.timestamp_ms == 18300
        assert result.screen_type == "lab_result"
        assert result.note_section_target == "investigations"
        assert result.integration_status == "injected"
        assert result.extracted_data is not None
        assert result.extracted_data.type == "lab_values"
        assert isinstance(result.extracted_data.values, list)
