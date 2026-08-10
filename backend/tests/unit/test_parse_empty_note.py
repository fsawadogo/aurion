"""#280 — empty-note detection that the Stage 1 guardrail keys off.

`parse_note_response` silently backfills missing / out-of-template sections
to `not_captured`, producing a `completeness == 0.0` note that used to ship
as a silent "success". These lock the detection signal (completeness 0 for an
empty note, > 0 for a real one) the transcription route's STAGE1_EMPTY_NOTE
audit relies on, and that the new event is a valid audit payload.
"""

from __future__ import annotations

from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType
from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.providers.note_gen.shared import parse_note_response


def _template() -> Template:
    return Template(
        key="orthopedic_surgery",
        display_name="Orthopedic Surgery",
        sections=[
            TemplateSection(id="chief_complaint", title="Chief Complaint", required=True),
            TemplateSection(id="physical_exam", title="Physical Examination", required=True),
            TemplateSection(id="plan", title="Plan", required=True),
        ],
    )


def _transcript() -> Transcript:
    return Transcript(
        session_id="00000000-0000-0000-0000-000000000000",
        provider_used="assemblyai",
        segments=[
            TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="Knee exam performed."),
        ],
    )


# AC-1 — model returns section ids OUTSIDE the template → all required
# sections backfilled to not_captured → empty note.
def test_out_of_template_ids_yield_empty():
    content = """{"sections": [
        {"id": "totally_made_up", "title": "X", "status": "populated",
         "claims": [{"id": "c1", "text": "t", "source_type": "transcript",
                     "source_id": "seg_001", "source_quote": "q"}]}
    ]}"""
    note = parse_note_response(content, _transcript(), _template(), stage=1, provider_name="anthropic")
    assert note.completeness_score == 0.0
    # Every required template section is present (backfilled) as not_captured.
    ids = {s.id for s in note.sections}
    assert {"chief_complaint", "physical_exam", "plan"}.issubset(ids)


# AC-2 — empty sections array → empty note.
def test_no_sections_yields_empty():
    note = parse_note_response('{"sections": []}', _transcript(), _template(), stage=1, provider_name="anthropic")
    assert note.completeness_score == 0.0


# AC-3 — a populated required section → non-zero completeness (guardrail
# must NOT misfire on a real note).
def test_populated_required_is_nonzero():
    content = """{"sections": [
        {"id": "chief_complaint", "title": "Chief Complaint", "status": "populated",
         "claims": [{"id": "c1", "text": "Right knee pain.", "source_type": "transcript",
                     "source_id": "seg_001", "source_quote": "knee"}]}
    ]}"""
    note = parse_note_response(content, _transcript(), _template(), stage=1, provider_name="anthropic")
    assert note.completeness_score > 0.0


# AC-4 — the new event is a valid, PHI-free audit payload.
def test_empty_note_event_allowlist():
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.STAGE1_EMPTY_NOTE]
    assert allowed == frozenset({"segment_count", "transcript_char_count", "completeness"})


# ── Malformed model output must NOT crash the whole note ─────────────────────
# Regression: the model occasionally emits a SECTION or a CLAIM as a bare
# string instead of an object; `.get()` on it raised
# `'str' object has no attribute 'get'` and failed the entire Stage-1 note
# (500 → STAGE1_FAILED). parse_note_response now skips the malformed entry and
# the template backfill recovers the section as not_captured.
def test_section_returned_as_string_is_skipped_not_crash():
    content = """{"sections": [
        "chief_complaint",
        {"id": "physical_exam", "title": "PE", "status": "populated",
         "claims": [{"id": "c1", "text": "Knee moves well.", "source_type": "transcript",
                     "source_id": "seg_001", "source_quote": "knee"}]}
    ]}"""
    note = parse_note_response(content, _transcript(), _template(), stage=1, provider_name="anthropic")
    ids = {s.id for s in note.sections}
    assert {"chief_complaint", "physical_exam", "plan"}.issubset(ids)
    pe = next(s for s in note.sections if s.id == "physical_exam")
    assert pe.status == "populated" and len(pe.claims) == 1


def test_claim_returned_as_string_is_skipped_not_crash():
    content = """{"sections": [
        {"id": "physical_exam", "title": "PE", "status": "populated",
         "claims": [
            "just a bare string claim",
            {"id": "c1", "text": "Tender medial joint line.", "source_type": "transcript",
             "source_id": "seg_001", "source_quote": "tender"}
         ]}
    ]}"""
    note = parse_note_response(content, _transcript(), _template(), stage=1, provider_name="anthropic")
    pe = next(s for s in note.sections if s.id == "physical_exam")
    # the bare-string claim is dropped; the valid one survives
    assert len(pe.claims) == 1
    assert pe.claims[0].text == "Tender medial joint line."


def test_non_dict_root_yields_empty_not_crash():
    # Model returned a JSON array instead of an object — must not crash.
    note = parse_note_response('["oops"]', _transcript(), _template(), stage=1, provider_name="anthropic")
    assert note.completeness_score == 0.0
    assert {"chief_complaint", "physical_exam", "plan"}.issubset({s.id for s in note.sections})
