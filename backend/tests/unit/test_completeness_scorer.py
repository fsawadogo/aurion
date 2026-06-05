"""Honest completeness scorer.

lane-backend/empty-transcript-guard.

Covers the six cases pinned by the lane brief:

  1. empty note → 0.0
  2. all not_captured → 0.0
  3. 2 of 3 populated → 2/3
  4. claims without source_id → not counted
  5. pending_video → not counted
  6. optional populated but required missing → counts only required

Plus a couple of bonus cases the brief implies but doesn't enumerate:

  * status="populated" with zero claims → not counted (the Marie
    bug — what motivated this lane)
  * a template with no required sections returns 0.0, not the
    pre-PR 1.0 (an empty-required template shouldn't claim
    "perfect completeness")
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.types import (
    Note,
    NoteClaim,
    NoteSection,
    Template,
    TemplateSection,
)
from app.modules.note_gen.service import (
    calculate_completeness,
    compute_session_stats,
    is_section_populated,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _claim(claim_id: str = "c1", source_id: str = "seg_001") -> NoteClaim:
    """A minimally valid NoteClaim — every test that wants a populated
    claim can use this without restating the four mandatory fields."""
    return NoteClaim(
        id=claim_id,
        text="Physician noted observation.",
        source_type="transcript",
        source_id=source_id,
        source_quote="observation",
    )


def _template(*sections: TemplateSection) -> Template:
    return Template(
        key="test_specialty",
        display_name="Test Specialty",
        sections=list(sections),
    )


def _note(*sections: NoteSection) -> Note:
    return Note(
        session_id="00000000-0000-0000-0000-000000000000",
        stage=1,
        provider_used="anthropic",
        specialty="test_specialty",
        sections=list(sections),
    )


# ── Case 1 — empty note → 0.0 ─────────────────────────────────────────────


def test_empty_note_returns_zero():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="hpi", title="HPI", required=True),
    )
    note = _note()  # no sections
    assert calculate_completeness(note, template) == 0.0


# ── Case 2 — all not_captured → 0.0 ───────────────────────────────────────


def test_all_not_captured_returns_zero():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="hpi", title="HPI", required=True),
        TemplateSection(id="pe", title="PE", required=True),
    )
    note = _note(
        NoteSection(id="cc", status="not_captured"),
        NoteSection(id="hpi", status="not_captured"),
        NoteSection(id="pe", status="not_captured"),
    )
    assert calculate_completeness(note, template) == 0.0


# ── Case 3 — 2 of 3 populated → 2/3 ───────────────────────────────────────


def test_two_of_three_populated_returns_two_thirds():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="hpi", title="HPI", required=True),
        TemplateSection(id="pe", title="PE", required=True),
    )
    note = _note(
        NoteSection(id="cc", status="populated", claims=[_claim("c1")]),
        NoteSection(id="hpi", status="populated", claims=[_claim("c2")]),
        NoteSection(id="pe", status="not_captured"),
    )
    score = calculate_completeness(note, template)
    assert abs(score - 2 / 3) < 1e-4


# ── Case 4 — claims without source_id → not counted ───────────────────────


def test_claim_without_source_id_is_rejected_at_pydantic_layer():
    """The pydantic ``NoteClaim`` model enforces ``min_length=1`` on
    ``source_id`` — a claim with no source can't even be constructed.
    This test pins that contract; the scorer's belt-and-braces check
    is exercised below using ``model_construct`` to bypass validation."""
    with pytest.raises(ValidationError):
        NoteClaim(
            id="c1",
            text="orphan claim",
            source_type="transcript",
            source_id="",  # rejected — min_length=1
        )


def test_scorer_rejects_claim_with_blank_source_id_at_runtime():
    """Even if a claim somehow lands without a valid source_id (e.g.
    a pre-validation legacy DynamoDB row), the scorer rejects it."""
    # ``model_construct`` bypasses pydantic validation so we can
    # build the deliberately-invalid section the scorer must reject.
    claim_bad = NoteClaim.model_construct(
        id="c_bad",
        text="orphan",
        source_type="transcript",
        source_id="   ",  # whitespace-only — bypasses min_length but is empty
        source_quote="",
        physician_edited=False,
        original_text=None,
    )
    section = NoteSection(id="cc", status="populated", claims=[claim_bad])
    assert is_section_populated(section) is False

    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
    )
    note = _note(section)
    assert calculate_completeness(note, template) == 0.0


# ── Case 5 — pending_video → not counted ──────────────────────────────────


def test_pending_video_status_is_not_populated():
    template = _template(
        TemplateSection(id="imaging_review", title="Imaging", required=True),
    )
    note = _note(
        NoteSection(id="imaging_review", status="pending_video", claims=[]),
    )
    assert calculate_completeness(note, template) == 0.0


def test_pending_video_does_not_count_even_with_a_claim():
    """A section with status=pending_video doesn't count even if a
    rogue claim landed on it — the scorer trusts the explicit status
    over the side-channel presence of a claim list."""
    template = _template(
        TemplateSection(id="imaging_review", title="Imaging", required=True),
    )
    note = _note(
        NoteSection(
            id="imaging_review",
            status="pending_video",
            claims=[_claim("c1")],
        ),
    )
    assert calculate_completeness(note, template) == 0.0


# ── Case 6 — optional populated, required missing → counts required only ──


def test_optional_populated_does_not_inflate_score_when_required_missing():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="optional_aside", title="Aside", required=False),
    )
    note = _note(
        NoteSection(id="cc", status="not_captured"),
        NoteSection(
            id="optional_aside", status="populated", claims=[_claim("c1")]
        ),
    )
    # 0 of 1 required → 0.0; the populated optional section is irrelevant.
    assert calculate_completeness(note, template) == 0.0


def test_only_required_sections_in_denominator():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="aside", title="Aside", required=False),
    )
    note = _note(
        NoteSection(id="cc", status="populated", claims=[_claim("c1")]),
    )
    # 1 of 1 required → 1.0
    assert calculate_completeness(note, template) == 1.0


# ── Marie's bug — status=populated with zero claims ───────────────────────


def test_populated_status_with_zero_claims_is_not_counted():
    """The pilot bug that motivated this lane: anthropic returned
    ``status="populated"`` sections with empty claim arrays when called
    against an empty transcript. The pre-PR scorer counted those as
    populated; the honest scorer rejects them."""
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="hpi", title="HPI", required=True),
    )
    note = _note(
        NoteSection(id="cc", status="populated", claims=[]),
        NoteSection(id="hpi", status="populated", claims=[]),
    )
    assert calculate_completeness(note, template) == 0.0


# ── Template with no required sections → 0.0, not 1.0 ─────────────────────


def test_template_with_no_required_sections_returns_zero():
    """Before this PR the scorer returned 1.0 when the template had no
    required sections, which made a completely empty template look
    perfect on the dashboard. The honest scorer returns 0.0."""
    template = _template(
        TemplateSection(id="aside", title="Aside", required=False),
    )
    note = _note(
        NoteSection(id="aside", status="populated", claims=[_claim("c1")]),
    )
    assert calculate_completeness(note, template) == 0.0


# ── compute_session_stats — the four-tuple every admin endpoint uses ──────


def test_compute_session_stats_returns_zero_tuple_for_none_note():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="hpi", title="HPI", required=True),
    )
    completeness, populated, required, provider = compute_session_stats(
        None, template
    )
    assert completeness == 0.0
    assert populated == 0
    assert required == 2
    assert provider == ""


def test_compute_session_stats_returns_provider_used_from_note():
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
    )
    note = _note(NoteSection(id="cc", status="populated", claims=[_claim()]))
    completeness, populated, required, provider = compute_session_stats(
        note, template
    )
    assert completeness == 1.0
    assert populated == 1
    assert required == 1
    assert provider == "anthropic"


def test_compute_session_stats_partial_completeness():
    """Same numbers as ``test_two_of_three_populated`` above, but
    through the full session-stats helper that the admin endpoint
    calls."""
    template = _template(
        TemplateSection(id="cc", title="CC", required=True),
        TemplateSection(id="hpi", title="HPI", required=True),
        TemplateSection(id="pe", title="PE", required=True),
    )
    note = _note(
        NoteSection(id="cc", status="populated", claims=[_claim("c1")]),
        NoteSection(id="hpi", status="populated", claims=[_claim("c2")]),
        NoteSection(id="pe", status="not_captured"),
    )
    completeness, populated, required, _ = compute_session_stats(note, template)
    assert populated == 2
    assert required == 3
    assert abs(completeness - 2 / 3) < 1e-4
