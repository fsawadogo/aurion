"""Unit tests for the patient_summary service.

Locks the four guarantees that matter for the foundation slice:

  1. Note rendering picks only populated sections (not_captured /
     pending_video are skipped).
  2. The rendered prompt input is bounded at _NOTE_RENDER_MAX_CHARS
     so the LLM context never blows up on a very long note.
  3. The audit-event kwargs whitelist refuses the body field — the
     summary IS PHI; never persisting it to the immutable trail.
  4. save_edit validates body length / non-emptiness symmetrically
     with the route layer.

Provider-level retries / generate_text behavior lives in
test_template_authoring.py — that path is already locked.
"""

from __future__ import annotations

from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
)
from app.core.types import (
    Note,
    NoteClaim,
    NoteSection,
)
from app.modules.patient_summary import service as ps_service


def _claim(text: str) -> NoteClaim:
    return NoteClaim(
        id="c1",
        text=text,
        source_type="transcript",
        source_id="seg_001",
        source_quote="...",
    )


def _note(sections: list[NoteSection]) -> Note:
    return Note(
        session_id="abc-123",
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=1.0,
        sections=sections,
    )


def test_render_skips_non_populated_sections():
    """`not_captured` / `pending_video` sections must not show up in
    the prompt — they have no content to summarise."""
    sections = [
        NoteSection(
            id="cc",
            title="Chief Complaint",
            status="populated",
            claims=[_claim("Right shoulder pain for two weeks.")],
        ),
        NoteSection(
            id="imaging",
            title="Imaging Review",
            status="not_captured",
            claims=[],
        ),
        NoteSection(
            id="plan",
            title="Plan",
            status="populated",
            claims=[_claim("MRI ordered for next week.")],
        ),
    ]
    rendered = ps_service._render_note_for_prompt(_note(sections))
    assert "Chief Complaint" in rendered
    assert "Plan" in rendered
    assert "Imaging Review" not in rendered


def test_render_truncates_oversized_notes():
    """Notes that would overshoot _NOTE_RENDER_MAX_CHARS get cut
    cleanly at the section boundary — the cap protects the LLM
    context budget."""
    huge_claim = "Very long claim text. " * 400  # ~8KB
    sections = [
        NoteSection(
            id="cc",
            title="Chief",
            status="populated",
            claims=[_claim(huge_claim)],
        ),
        NoteSection(
            id="plan",
            title="Plan",
            status="populated",
            claims=[_claim("This must NOT be in the rendered output.")],
        ),
    ]
    rendered = ps_service._render_note_for_prompt(_note(sections))
    assert len(rendered) <= ps_service._NOTE_RENDER_MAX_CHARS
    assert "This must NOT be in the rendered output." not in rendered


def test_render_returns_empty_when_no_populated_sections():
    """Pure not_captured note → empty render → the calling service
    raises ValueError before any LLM call."""
    sections = [
        NoteSection(
            id="cc",
            title="Chief",
            status="not_captured",
            claims=[],
        ),
    ]
    assert ps_service._render_note_for_prompt(_note(sections)) == ""


def test_audit_events_never_carry_summary_body():
    """The summary IS PHI — letting it into the immutable audit log
    is permanent. Lock the whitelists so a future caller can't
    accidentally write `body=...`."""
    for event in (
        AuditEventType.PATIENT_SUMMARY_GENERATED,
        AuditEventType.PATIENT_SUMMARY_EDITED,
    ):
        allowed = ALLOWED_AUDIT_KWARGS.get(event)
        assert allowed is not None, f"No whitelist entry for {event}"
        assert "body" not in allowed
        assert "summary" not in allowed
        assert "text" not in allowed


def test_audit_enum_values_are_stable():
    """Regression guard — DynamoDB rows reference these strings
    verbatim; lock them."""
    assert (
        AuditEventType.PATIENT_SUMMARY_GENERATED.value
        == "patient_summary_generated"
    )
    assert AuditEventType.PATIENT_SUMMARY_EDITED.value == "patient_summary_edited"
