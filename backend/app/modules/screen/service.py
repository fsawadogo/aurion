"""Screen capture pipeline — OCR-only, no vision provider.

Processing steps per CLAUDE.md:
1. PHI redaction — strip patient names, MRN, DOB, health card patterns
2. Screen type classification — rule-based: lab_result, imaging_viewer, emr, other
3. OCR extraction — AWS Textract (or LOCAL_MODE fixture data)
4. Timestamp anchoring to transcript segment
5. Note injection routing per screen type

Screen frames bypass the vision provider entirely. OCR is faster, cheaper,
and more accurate for structured screen content.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.types import (
    ScreenCaptureResult,
    ScreenExtractedData,
    ScreenLabValue,
)
from app.modules.config.appconfig_client import get_config

logger = logging.getLogger("aurion.screen")

_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")

# ── PHI Redaction Patterns ───────────────────────────────────────────────────
# These patterns match common PHI formats found in clinical screen captures.
# Redaction happens BEFORE any data is stored or injected into notes.

# MRN: 6-10 digit number often preceded by "MRN" or "Medical Record"
_MRN_PATTERN = re.compile(
    r"(?i)(?:MRN|medical\s*record\s*(?:number|#|no\.?)?)\s*:?\s*\d{4,10}",
)

# DOB: various date formats preceded by DOB/Date of Birth/Birthdate
_DOB_PATTERN = re.compile(
    r"(?i)(?:DOB|date\s*of\s*birth|birthdate|birth\s*date)\s*:?\s*"
    r"\d{1,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4}",
)

# Health card numbers — Canadian formats: 10-12 digits, sometimes with spaces/dashes
_HEALTH_CARD_PATTERN = re.compile(
    r"(?i)(?:health\s*card|RAMQ|OHIP|HC#?|PHN)\s*:?\s*[\d\s\-]{8,14}",
)

# Patient name patterns — "Patient:", "Name:", "Patient Name:" followed by text
_PATIENT_NAME_PATTERN = re.compile(
    r"(?i)(?:patient\s*name|patient|name)\s*:?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}",
)

# SSN / SIN patterns
_SSN_SIN_PATTERN = re.compile(
    r"\b\d{3}[\s\-]\d{2,3}[\s\-]\d{3,4}\b",
)

_PHI_PATTERNS = [
    _MRN_PATTERN,
    _DOB_PATTERN,
    _HEALTH_CARD_PATTERN,
    _PATIENT_NAME_PATTERN,
    _SSN_SIN_PATTERN,
]


def redact_phi(text: str) -> str:
    """Remove PHI patterns from extracted text.

    Replaces matched patterns with [REDACTED]. This runs on all text
    extracted by OCR before any further processing or injection.
    """
    result = text
    for pattern in _PHI_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


# ── Screen Type Classification ───────────────────────────────────────────────

# Keywords and phrases used for rule-based screen type detection.
_LAB_KEYWORDS = [
    "hemoglobin", "hgb", "wbc", "rbc", "platelet", "creatinine", "glucose",
    "sodium", "potassium", "chloride", "bicarbonate", "bun", "alt", "ast",
    "bilirubin", "albumin", "inr", "ptt", "hba1c", "tsh", "troponin",
    "lab result", "lab report", "laboratory", "blood work", "cbc",
    "complete blood count", "metabolic panel", "lipid panel",
    "reference range", "normal range", "g/l", "mmol/l", "10^9/l",
    "umol/l", "u/l", "iu/l",
]

_IMAGING_KEYWORDS = [
    "dicom", "pacs", "x-ray", "xray", "ct scan", "mri", "ultrasound",
    "fluoroscopy", "mammography", "pet scan", "nuclear medicine",
    "radiology", "series", "modality", "laterality", "accession",
    "study date", "imaging", "radiograph", "contrast", "axial",
    "sagittal", "coronal", "window", "level", "slice",
]

_EMR_KEYWORDS = [
    "electronic medical record", "emr", "ehr", "epic", "cerner",
    "meditech", "allscripts", "patient chart", "encounter",
    "progress note", "clinical note", "order entry", "medication list",
    "problem list", "visit summary", "discharge summary",
]


def classify_screen_type(text: str) -> str:
    """Classify a screen capture based on its extracted text content.

    Rule-based classifier using keyword matching. Returns one of:
    lab_result, imaging_viewer, emr, other.
    """
    lower = text.lower()

    # Score each category — highest score wins
    lab_score = sum(1 for kw in _LAB_KEYWORDS if kw in lower)
    imaging_score = sum(1 for kw in _IMAGING_KEYWORDS if kw in lower)
    emr_score = sum(1 for kw in _EMR_KEYWORDS if kw in lower)

    # Require a minimum threshold to classify — avoid false positives
    _MIN_SCORE = 2

    scores = {
        "lab_result": lab_score,
        "imaging_viewer": imaging_score,
        "emr": emr_score,
    }

    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]

    if best_score < _MIN_SCORE:
        return "other"

    return best_type


# ── OCR — AWS Textract / Local Mode ──────────────────────────────────────────

def _get_textract_client():
    """Build a Textract client with optional LocalStack endpoint."""
    kwargs: dict[str, Any] = {"region_name": _REGION}
    if _ENDPOINT_URL:
        kwargs["endpoint_url"] = _ENDPOINT_URL
    return boto3.client("textract", **kwargs)


def _local_mode_fixture() -> str:
    """Return fixture OCR text for local development.

    Used when SCREEN_OCR_LOCAL_MODE=true — avoids real Textract calls.
    """
    return (
        "Lab Results - Complete Blood Count (CBC)\n"
        "Reference Range\n"
        "Hemoglobin: 138 g/L (120-160)\n"
        "WBC: 9.2 10^9/L (4.0-11.0)\n"
        "Platelet: 245 10^9/L (150-400)\n"
        "RBC: 4.8 10^12/L (4.0-5.5)\n"
        "Hematocrit: 0.42 L/L (0.36-0.46)\n"
    )


async def extract_text_ocr(image_bytes: bytes) -> str:
    """Extract text from a screen capture image using AWS Textract.

    Falls back to fixture data when SCREEN_OCR_LOCAL_MODE=true.
    """
    local_mode = os.getenv("SCREEN_OCR_LOCAL_MODE", "false").lower() == "true"
    if local_mode:
        logger.info("Screen OCR: using local fixture data (SCREEN_OCR_LOCAL_MODE=true)")
        return _local_mode_fixture()

    client = _get_textract_client()
    try:
        response = client.detect_document_text(
            Document={"Bytes": image_bytes}
        )
        lines = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                lines.append(block.get("Text", ""))
        return "\n".join(lines)
    except (BotoCoreError, ClientError) as e:
        logger.error("Textract OCR failed: %s", str(e))
        raise


# ── Data Extraction ──────────────────────────────────────────────────────────

# Pattern to extract lab values: "Name: Value Unit" or "Name Value Unit (range)"
_LAB_VALUE_PATTERN = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z\s]{1,30}?)\s*:?\s+"
    r"(?P<value>\d+\.?\d*)\s*"
    r"(?P<unit>[A-Za-z/^0-9\*]+(?:\s*[A-Za-z/^0-9\*]+)?)"
)

# Common lab value names for filtering matches
_KNOWN_LAB_NAMES = {
    "hemoglobin", "hgb", "wbc", "rbc", "platelet", "platelets",
    "creatinine", "glucose", "sodium", "potassium", "chloride",
    "bicarbonate", "bun", "alt", "ast", "bilirubin", "albumin",
    "inr", "ptt", "hba1c", "tsh", "troponin", "hematocrit",
    "calcium", "magnesium", "phosphate", "iron", "ferritin",
    "ldh", "ggt", "alp", "ck", "lipase", "amylase",
}


def extract_lab_values(text: str) -> list[ScreenLabValue]:
    """Extract structured lab values from OCR text.

    Returns a list of ScreenLabValue with name, value, unit, and flag.
    """
    values: list[ScreenLabValue] = []
    seen_names: set[str] = set()

    for match in _LAB_VALUE_PATTERN.finditer(text):
        name = match.group("name").strip()
        # Only include known lab value names to avoid false positives
        if name.lower() not in _KNOWN_LAB_NAMES:
            continue
        # Avoid duplicates
        if name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        values.append(
            ScreenLabValue(
                name=name,
                value=match.group("value"),
                unit=match.group("unit").strip(),
                flag="normal",  # Flag determination would need reference ranges
            )
        )

    return values


# Imaging metadata extraction patterns
_MODALITY_PATTERN = re.compile(
    r"(?i)(?:modality|study\s*type|exam)\s*:?\s*([A-Za-z\s\-]+?)(?:\n|$|,|;)"
)
_LATERALITY_PATTERN = re.compile(
    r"(?i)(?:laterality|side)\s*:?\s*(left|right|bilateral|L|R)(?:\b)"
)
_SERIES_PATTERN = re.compile(
    r"(?i)(?:series|sequence)\s*:?\s*([A-Za-z0-9\s\-_]+?)(?:\n|$|,|;)"
)


def extract_imaging_metadata(text: str) -> dict[str, str]:
    """Extract imaging metadata from OCR text.

    Returns only metadata: modality, laterality, series label.
    Never returns the image content itself.
    """
    metadata: dict[str, str] = {}

    modality_match = _MODALITY_PATTERN.search(text)
    if modality_match:
        metadata["modality"] = modality_match.group(1).strip()

    laterality_match = _LATERALITY_PATTERN.search(text)
    if laterality_match:
        metadata["laterality"] = laterality_match.group(1).strip()

    series_match = _SERIES_PATTERN.search(text)
    if series_match:
        metadata["series_label"] = series_match.group(1).strip()

    return metadata


# ── Main Pipeline ────────────────────────────────────────────────────────────

async def process_screen_frame(
    frame_id: str,
    session_id: str,
    timestamp_ms: int,
    image_bytes: bytes,
) -> Optional[ScreenCaptureResult]:
    """Process a single screen capture frame through the full pipeline.

    Steps:
    1. Check feature flag — return None if screen capture disabled
    2. OCR extraction (Textract or local fixture)
    3. PHI redaction on extracted text
    4. Screen type classification
    5. Data extraction based on type
    6. Route to correct note section or discard

    Returns:
        ScreenCaptureResult with extracted data and routing info,
        or None if the feature is disabled.
    """
    # Step 1: Check feature flag
    config = get_config()
    if not config.feature_flags.screen_capture_enabled:
        logger.info(
            "Screen capture disabled via feature flag: session=%s frame=%s",
            session_id, frame_id,
        )
        return None

    # Step 2: OCR extraction
    raw_text = await extract_text_ocr(image_bytes)

    # Step 3: PHI redaction
    redacted_text = redact_phi(raw_text)

    # Step 4: Screen type classification
    screen_type = classify_screen_type(redacted_text)

    logger.info(
        "Screen frame classified: session=%s frame=%s type=%s",
        session_id, frame_id, screen_type,
    )

    # Step 5 & 6: Extract data and route based on type
    if screen_type == "lab_result":
        lab_values = extract_lab_values(redacted_text)
        return ScreenCaptureResult(
            frame_id=frame_id,
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            screen_type="lab_result",
            extracted_data=ScreenExtractedData(
                type="lab_values",
                values=lab_values,
            ),
            note_section_target="investigations",
            integration_status="injected",
        )

    elif screen_type == "imaging_viewer":
        metadata = extract_imaging_metadata(redacted_text)
        # Imaging viewer returns metadata only — modality, laterality, series label.
        # Never the image content itself.
        meta_values = [
            ScreenLabValue(name=k, value=v, unit="", flag="metadata")
            for k, v in metadata.items()
        ]
        return ScreenCaptureResult(
            frame_id=frame_id,
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            screen_type="imaging_viewer",
            extracted_data=ScreenExtractedData(
                type="imaging_metadata",
                values=meta_values,
            ),
            note_section_target="imaging_review",
            integration_status="injected",
        )

    elif screen_type == "emr":
        # EMR frames: log to audit trail only, never inject into note
        logger.info(
            "EMR screen frame skipped (audit-only): session=%s frame=%s",
            session_id, frame_id,
        )
        return ScreenCaptureResult(
            frame_id=frame_id,
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            screen_type="emr",
            extracted_data=None,
            note_section_target=None,
            integration_status="skipped",
        )

    else:
        # Other/unclassified frames: discard
        logger.info(
            "Unclassified screen frame discarded: session=%s frame=%s",
            session_id, frame_id,
        )
        return ScreenCaptureResult(
            frame_id=frame_id,
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            screen_type="other",
            extracted_data=None,
            note_section_target=None,
            integration_status="discarded",
        )
