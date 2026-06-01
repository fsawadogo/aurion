"""Unit tests for the FHIR DocumentReference serializer (#57).

Locks the wire-format invariants: structure, embedded LOINC code,
patient identifier handling, plain-text rendering, base64 payload.
"""

from __future__ import annotations

import base64
import json

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.emr.fhir import (
    render_note_plain_text,
    serialize_document_reference,
    serialize_payload,
    synthetic_external_id,
)


def _note(specialty: str = "orthopedic_surgery") -> Note:
    """Minimal Note fixture — two populated sections, one empty."""
    return Note(
        session_id="11111111-1111-1111-1111-111111111111",
        stage=2,
        version=1,
        provider_used="anthropic",
        specialty=specialty,
        completeness_score=0.8,
        sections=[
            NoteSection(
                id="hpi",
                title="History of Present Illness",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c001",
                        text="Patient reports right knee pain for 3 weeks.",
                        source_type="transcript",
                        source_id="seg_001",
                    ),
                    NoteClaim(
                        id="c002",
                        text="Pain worsens with weight-bearing.",
                        source_type="transcript",
                        source_id="seg_002",
                    ),
                ],
            ),
            NoteSection(
                id="physical_exam",
                title="Physical Exam",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c003",
                        text="Tenderness over medial joint line.",
                        source_type="transcript",
                        source_id="seg_005",
                    ),
                ],
            ),
            NoteSection(
                id="imaging_review",
                title="Imaging Review",
                status="not_captured",
                claims=[],
            ),
        ],
    )


# ── render_note_plain_text ───────────────────────────────────────────────


def test_render_plain_text_includes_populated_sections():
    out = render_note_plain_text(_note())
    assert "# History of Present Illness" in out
    assert "# Physical Exam" in out
    assert "Patient reports right knee pain" in out
    assert "Tenderness over medial joint line." in out


def test_render_plain_text_skips_unpopulated_sections():
    """`not_captured` sections must not appear in the wire payload."""
    out = render_note_plain_text(_note())
    assert "Imaging Review" not in out
    assert "imaging_review" not in out


def test_render_plain_text_trailing_newline():
    """Rendered output ends with a single newline — predictable for
    diffing + fingerprinting."""
    out = render_note_plain_text(_note())
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


# ── serialize_document_reference ─────────────────────────────────────────


def test_serialize_basic_shape():
    doc = serialize_document_reference(
        "sess-123",
        _note(),
        author_user_id="user-456",
    )
    assert doc["resourceType"] == "DocumentReference"
    assert doc["status"] == "current"
    assert doc["author"] == [{"reference": "Practitioner/user-456"}]
    # LOINC clinical note code is the conservative default
    assert doc["type"]["coding"][0]["code"] == "11506-3"
    assert doc["type"]["coding"][0]["system"] == "http://loinc.org"


def test_serialize_carries_session_identifier():
    """Identifier system + value let downstream systems group by
    Aurion session without parsing the body."""
    doc = serialize_document_reference(
        "sess-abc", _note(), author_user_id="user-1",
    )
    ident = doc["identifier"][0]
    assert ident["system"] == "urn:aurion:session"
    assert ident["value"] == "sess-abc"


def test_serialize_embeds_base64_plaintext():
    """The note's content rides in attachment.data as base64 plain text."""
    doc = serialize_document_reference(
        "sess-1", _note(), author_user_id="user-1",
    )
    attachment = doc["content"][0]["attachment"]
    assert attachment["contentType"] == "text/plain"
    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
    assert "# History of Present Illness" in decoded
    assert "# Physical Exam" in decoded


def test_serialize_specialty_lands_in_context():
    """Specialty metadata goes in DocumentReference.context.related
    so it doesn't trip the EMR's category column."""
    doc = serialize_document_reference(
        "s", _note(specialty="plastic_surgery"), author_user_id="u",
    )
    related = doc["context"]["related"][0]["identifier"]
    assert related["system"] == "urn:aurion:specialty"
    assert related["value"] == "plastic_surgery"


def test_serialize_omits_context_when_specialty_empty():
    """Empty specialty → no `context` key at all (cleanest payload)."""
    note = _note()
    note.specialty = ""
    doc = serialize_document_reference("s", note, author_user_id="u")
    assert "context" not in doc


def test_serialize_includes_subject_with_external_identifier():
    """external_reference_id surfaces as DocumentReference.subject.identifier."""
    doc = serialize_document_reference(
        "s",
        _note(),
        author_user_id="u",
        external_reference_id="MRN-12345",
    )
    subj = doc["subject"]["identifier"]
    assert subj["system"] == "urn:aurion:patient-identifier"
    assert subj["value"] == "MRN-12345"


def test_serialize_omits_subject_when_no_identifier():
    """No identifier → no `subject` key (EMR will use other heuristics
    or reject; that's the connector's problem, not the serializer's)."""
    doc = serialize_document_reference(
        "s", _note(), author_user_id="u",
    )
    assert "subject" not in doc


# ── serialize_payload ────────────────────────────────────────────────────


def test_serialize_payload_returns_json_bytes():
    payload = serialize_payload(
        "sess-1", _note(), author_user_id="user-1",
    )
    assert isinstance(payload, bytes)
    # Parses back to the same dict
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed["resourceType"] == "DocumentReference"


def test_serialize_payload_deterministic_size_floor():
    """A populated note → payload at least 600 bytes (LOINC coding +
    base64 body of three claims). Sanity floor against accidental
    empty serialization."""
    payload = serialize_payload(
        "sess-1", _note(), author_user_id="user-1",
    )
    assert len(payload) > 600


def test_serialize_payload_ends_with_newline():
    """Newline-terminated for log readability + connector convenience."""
    payload = serialize_payload(
        "sess-1", _note(), author_user_id="user-1",
    )
    assert payload.endswith(b"\n")


# ── synthetic_external_id ────────────────────────────────────────────────


def test_synthetic_external_id_includes_session_prefix():
    eid = synthetic_external_id("abc-def")
    assert eid.startswith("stub-abc-def-")
    # Random suffix is 8 hex chars
    assert len(eid) == len("stub-abc-def-") + 8


def test_synthetic_external_id_is_unique_per_call():
    """Random component varies — two calls with the same session
    produce different ids."""
    a = synthetic_external_id("s")
    b = synthetic_external_id("s")
    assert a != b
