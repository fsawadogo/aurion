"""Grounded Lab DOCX export renders each comparison shape to valid .docx bytes.

The endpoint formats the already-computed result the client is displaying — it
never re-runs anything — so these lock the builder: each of the three result
shapes (grounded pairs, fusion notes, modality notes incl. a null visual note)
produces a non-empty, valid DOCX (a zip container, ``PK`` signature), and a
sparse/partial payload downgrades gracefully instead of crashing.
"""

from __future__ import annotations

from app.api.v1.admin.grounded_lab import _build_comparison_docx


def _is_docx(b: bytes) -> bool:
    return b[:2] == b"PK" and len(b) > 500  # OOXML is a zip container


def test_grounded_shape_exports_valid_docx() -> None:
    result = {
        "frame_count": 3,
        "descriptive_findings": 2,
        "grounded_findings": 1,
        "evidence_mode": "hybrid",
        "provider_used": "gemini",
        "pairs": [
            {
                "frame_id": "frame_1",
                "timestamp_ms": 65000,
                "audio_anchor_id": "seg_0",
                "evidence_kind": "frame",
                "descriptive": {
                    "text": "knee flexed ~110 degrees",
                    "confidence": "low",
                    "integration_status": "ENRICHES",
                },
                "grounded": None,
            },
        ],
    }
    assert _is_docx(_build_comparison_docx("grounded", "Test — orthopedic", result))


def test_fusion_shape_exports_valid_docx() -> None:
    note = {
        "sections": [
            {
                "id": "hpi",
                "title": "History of Present Illness",
                "claims": [
                    {"id": "c1", "text": "left knee pain", "source_type": "transcript"}
                ],
            }
        ]
    }
    result = {
        "frame_count": 5,
        "sections_a": 1,
        "sections_b": 1,
        "conflicts_b": 0,
        "note_a": note,
        "note_b": note,
    }
    assert _is_docx(_build_comparison_docx("fusion", "Test", result))


def test_modality_shape_with_null_visual_exports_valid_docx() -> None:
    note = {
        "sections": [
            {
                "id": "cc",
                "title": "Chief Complaint",
                "claims": [
                    {"id": "c1", "text": "knee pain", "source_type": "transcript"}
                ],
            }
        ]
    }
    result = {
        "frame_count": 4,
        "sections_audio": 1,
        "sections_visual": 0,
        "sections_merged": 1,
        "note_audio": note,
        "note_visual": None,  # video yielded nothing — must not crash
        "note_merged": note,
    }
    assert _is_docx(_build_comparison_docx("modality", "Test", result))


def test_sparse_payload_downgrades_without_crashing() -> None:
    # Missing optional keys / no pairs — still a valid document.
    assert _is_docx(_build_comparison_docx("grounded", "", {"frame_count": 0}))
