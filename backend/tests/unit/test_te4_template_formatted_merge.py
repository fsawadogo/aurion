"""TE-4 — the merge routes by the template and builds the claim.

TE-3 aimed the CAPTURE. The merge was still `text=caption.visual_description`
verbatim into a section chosen from a hardcoded id tuple.

**This file is mostly a record of a design that was wrong twice.** Review
found three blockers in the first cut, and the fixes are what these tests now
pin:

  * Routing inferred "this section receives images" from "this section HAS
    trigger keywords". Measured against the shipped templates, that filed a
    wound photo under `vital_signs` (emergency), `past_medical_history`
    (family/internal medicine) and `developmental_history` (paediatrics).
    `visual_trigger_keywords` are SPOKEN PHRASES — "looking at", "you can
    see", "right here" — so they are matched against the anchor's transcript
    text, which is the one job the field was defined for.
  * A regex DELETED captions that "reported nothing relevant". It was an
    unanchored search over free text, so multi-clause captions lost their
    other clauses: "Bone is not visible at the base of the ulcer" (an ulcer
    grading determinant) and "The left knee is not visible; the right knee
    shows a 4cm effusion" were both destroyed. Silent data loss in a chart.
    Removed entirely — the pipeline already drops low-confidence captions
    before merge, so the prompt asks for low confidence instead.
  * Hoisting the routing out of the apply loop is itself an output change, so
    it is gated; OFF keeps the legacy in-loop routing byte-identical.

And the fourth, subtler one: capture-time prediction was not passing
`template`, so capture and placement routed through different tiers — a wider
divergence than the one TE-4 set out to close.
"""

from __future__ import annotations

import pytest

from app.core.types import (
    FrameCaption,
    Note,
    NoteClaim,
    NoteSection,
    Template,
    TemplateSection,
)
from app.modules.vision.service import (
    _find_target_section,
    _format_visual_claim_text,
    _section_focus_block,
    _template_section_for_anchor_text,
    merge_visual_citations,
)

WOUND_TALK = "let me take a look at this wound"


def _caption(
    frame_id: str = "f1",
    description: str = "A healing incision with clean margins",
    status: str = "ENRICHES",
    anchor: str = "seg_014",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id, session_id="s1", timestamp_ms=1000,
        audio_anchor_id=anchor, provider_used="anthropic",
        visual_description=description, confidence="high",
        integration_status=status,
    )


def _note_with_anchor() -> Note:
    """Tier-1 routing: wound_assessment holds the anchor claim."""
    return Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery",
        sections=[
            NoteSection(id="chief_complaint", title="Chief complaint",
                        status="populated", claims=[]),
            NoteSection(
                id="wound_assessment", title="Wound assessment",
                status="populated",
                claims=[NoteClaim(id="c2", text="Physician described the wound.",
                                  source_type="transcript", source_id="seg_014")],
            ),
        ],
    )


def _custom_note() -> Note:
    """Custom ids, none in the legacy tuple, both pending_video — so every
    unanchored caption lands in the status-reading last tier. This is the
    shape that exposed the prediction/placement divergence."""
    return Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery",
        sections=[
            NoteSection(id="lipo_360_technique", title="Technique",
                        status="pending_video", claims=[]),
            NoteSection(id="donor_site", title="Donor site",
                        status="pending_video", claims=[]),
        ],
    )


def _keyless_template() -> Template:
    """No trigger keywords, so routing falls past the template tier.

    Load-bearing: the divergence is a LAST-tier phenomenon, because that tier
    is the only one reading `status`. A template whose keywords match sends
    the caption to the template tier, which is status-independent, and the bug
    becomes unreachable — an earlier draft of these tests did exactly that and
    passed against the unfixed code.
    """
    return Template(
        key="custom", display_name="Custom",
        sections=[
            TemplateSection(id="lipo_360_technique", title="Technique",
                            description="Operative technique as observed."),
            TemplateSection(id="donor_site", title="Donor site",
                            description="Donor site appearance."),
        ],
    )


def _keyed_template() -> Template:
    return Template(
        key="custom", display_name="Custom",
        sections=[
            TemplateSection(id="lipo_360_technique", title="Technique",
                            description="Operative technique.",
                            visual_trigger_keywords=["cannula", "technique"]),
            TemplateSection(id="donor_site", title="Donor site",
                            description="Donor site appearance.",
                            visual_trigger_keywords=["donor site", "graft"]),
        ],
    )


# ── AC-1 · the claim is built, not pasted ───────────────────────────────────


def test_claim_text_is_constructed_but_traceability_is_unchanged():
    """AC-1 — the text changes; the citation does not."""
    note = _note_with_anchor()
    caption = _caption(description="The image shows a healing incision")

    merge_visual_citations(note, [caption], _keyed_template())

    claim = note.get_section("wound_assessment").claims[-1]
    assert claim.text != caption.visual_description
    assert claim.source_type == "visual"
    assert claim.source_id == "f1"
    assert claim.id == "vclaim_f1"
    assert "f1" in claim.source_quote


# ── AC-2 · engine OFF is byte-identical ─────────────────────────────────────


@pytest.mark.parametrize(
    "description,status",
    [
        ("The image shows a healing incision", "ENRICHES"),
        ("nothing relevant is visible in this frame", "ENRICHES"),
        ("the photo depicts erythema", "CONFLICTS"),
        ("no trailing period", "ENRICHES"),
    ],
)
def test_engine_off_reproduces_the_pre_te4_claim_exactly(description, status):
    """AC-2 (text) — `template=None` produces the byte-for-byte pre-TE-4 claim.

    Expectations transcribed from the old implementation, not from the new
    one. The formatter initially ran unconditionally, which would have
    silently reworded every note while the engine was nominally dark.
    """
    caption = _caption(description=description, status=status)
    note = _note_with_anchor()
    merge_visual_citations(note, [caption], None)
    got = note.get_section("wound_assessment").claims[-1]

    if status == "ENRICHES":
        assert got.id == f"vclaim_{caption.frame_id}"
        assert got.text == caption.visual_description
    else:
        assert got.id == f"conflict_{caption.frame_id}"
        assert got.text == (
            "CONFLICT: Visual observation differs from audio — "
            f"{caption.visual_description}"
        )
    assert got.source_type == "visual"
    assert got.source_id == caption.frame_id


def test_engine_off_preserves_legacy_in_loop_routing():
    """AC-2 (structure) — the case review used to prove hoisting is itself an
    output change.

    One pending_video section, two ENRICHES captions. The old loop routed
    caption 1 there, flipped it to `populated`, then found NO pending_video
    section for caption 2 and dropped it. Hoisting would land both. A claim
    that does not exist today must not appear while the engine is dark.
    """
    note = Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery",
        sections=[NoteSection(id="operative_findings", title="Findings",
                              status="pending_video", claims=[])],
    )

    merge_visual_citations(
        note,
        [_caption(frame_id="f1", anchor="seg_a"),
         _caption(frame_id="f2", anchor="seg_b")],
        None,
    )

    ids = [c.source_id for c in note.sections[0].claims]
    assert ids == ["f1"], "engine OFF must drop f2 exactly as the old loop did"


def test_engine_off_keeps_the_legacy_section_tuple():
    """AC-2 — routing with no template still uses the built-in visual
    sections, so notes built without the engine land where they always did."""
    note = Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery",
        sections=[
            NoteSection(id="hpi", title="HPI", status="populated", claims=[]),
            NoteSection(id="physical_exam", title="Exam",
                        status="populated", claims=[]),
        ],
    )
    assert _find_target_section(note, "seg_zzz", None).id == "physical_exam"


# ── AC-3 · no-finding captions, handled where they belong ───────────────────


def test_focus_block_asks_for_low_confidence_not_a_description():
    """AC-3 — the mechanism that replaced a regex deleting chart text.

    TE-3's block tells the model to say so when nothing relevant is visible,
    which GUARANTEES such captions exist. The first fix pattern-matched them
    in the merge and dropped them — an unanchored regex over free text that
    also destroyed "Bone is not visible at the base of the ulcer" and
    "The left knee is not visible; the right knee shows a 4cm effusion".

    The pipeline already drops `confidence == "low"` before merge
    (`api/v1/vision.py`), so the prompt routes the case into that existing,
    non-destructive path instead.
    """
    template = Template(
        key="c", display_name="C",
        sections=[TemplateSection(id="wound_assessment", title="Wound",
                                  description="Wound margins as observed.")],
    )
    note = Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery",
        sections=[NoteSection(id="wound_assessment", title="Wound",
                              status="pending_video", claims=[])],
    )

    block = _section_focus_block(template, note, "seg_1")

    assert block is not None
    assert 'confidence "low"' in block
    assert "do not describe the scene instead" in block


def test_merge_never_deletes_a_caption_for_its_wording():
    """AC-3 — the merge must have NO content-based deletion path at all.

    Each of these fired the removed regex. Every one is a real clinical
    observation; several carry the only measurement in the caption.
    """
    destroyed_before = [
        "Bone is not visible at the base of the ulcer.",
        "Necrotic tissue is not visible; the wound bed is uniformly pink.",
        "Unable to assess wound depth; margins are clean and approximated.",
        "The left knee is not visible; the right knee shows a 4cm effusion.",
        "There is no visible evidence of infection at the port site.",
        "The mole borders are not discernible; diameter approximately 8mm.",
    ]
    for description in destroyed_before:
        note = _note_with_anchor()
        merge_visual_citations(
            note, [_caption(description=description)], _keyed_template()
        )
        claims = note.get_section("wound_assessment").claims
        assert any(c.source_type == "visual" for c in claims), (
            f"caption was silently deleted from the note: {description!r}"
        )


# ── AC-4 · the image-caption voice ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("The image shows a healing incision", "A healing incision."),
        ("This frame shows mild erythema", "Mild erythema."),
        ("In this image, the wound bed is pink", "The wound bed is pink."),
        ("The photo depicts a clean dressing", "A clean dressing."),
        ("Visible in this frame is a surgical drain", "A surgical drain."),
        ("Mild swelling at the lateral border", "Mild swelling at the lateral border."),
        ("A healing incision with clean margins.",
         "A healing incision with clean margins."),
    ],
)
def test_image_meta_openers_are_stripped(raw: str, expected: str):
    """AC-4 — "The image shows X" describes the MEDIUM. The note wants X."""
    assert _format_visual_claim_text(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "This image shows that the drain is patent",
        "The photo displays that the site is clean",
    ],
)
def test_hedged_openers_are_left_alone(raw: str):
    """AC-4 (safety) — "shows THAT X" scopes the claim to what one frame
    showed. Dropping the scope asserts X about the patient, which strengthens
    a claim without adding a word — so "it only removes words" does not cover
    it. Descriptive mode says leave it hedged.
    """
    assert _format_visual_claim_text(raw).startswith(raw.split(" ")[0].capitalize())
    assert "that" in _format_visual_claim_text(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "mg/dL glucose reading of 110 on the meter",
        "pH strip reads 7.4",
        "pRBC transfusion tubing in place",
        "α-angle measured at 55 degrees",
        "mLs of serosanguinous fluid in the drain",
    ],
)
def test_sentence_case_never_corrupts_a_clinical_token(raw: str):
    """AC-4 (safety) — naive capitalisation turned `mg/dL` into `Mg/dL`, and
    **Mg is magnesium**: a unit silently became a different analyte. Same for
    `pH`→`PH`, `pRBC`→`PRBC`, and `α-angle`→`Α-angle` (U+0391), where
    alpha-angle is a hip-impingement measurement the ortho pilot uses."""
    out = _format_visual_claim_text(raw)
    assert out.startswith(raw.split(" ")[0]), f"{raw!r} -> {out!r}"


def test_ordinary_prose_is_still_sentence_cased():
    """…while the common case still reads like a sentence."""
    assert _format_visual_claim_text("mild erythema present") == (
        "Mild erythema present."
    )


def test_terminal_punctuation_is_not_doubled():
    """A caption already ending in punctuation must not gain a stray period —
    an earlier version accepted only ".?!" and produced "The incision:."."""
    assert _format_visual_claim_text("The image shows the incision:") == (
        "The incision:"
    )


def test_formatter_only_removes_never_adds():
    """Every word of the output appears in the input. Necessary but NOT
    sufficient — hedge removal passes this too, which is why
    `test_hedged_openers_are_left_alone` exists separately."""
    raw = "The image shows a 3cm laceration with surrounding erythema"
    out = _format_visual_claim_text(raw)
    src = raw.lower()
    for word in out.rstrip(".").lower().split():
        assert word in src, f"formatter invented {word!r}"


@pytest.mark.parametrize("raw", ["The image shows", "In this image,", ""])
def test_stripping_never_empties_a_claim(raw: str):
    """Degradation — whatever else happens, the merge must not emit a claim
    with no text. Asserts the intent (content survives) rather than an exact
    string, so punctuation normalisation is free to change."""
    out = _format_visual_claim_text(raw)
    # Non-empty in, non-empty out — the guard exists so a caption that is
    # nothing but an opener falls back to itself instead of vanishing.
    assert bool(out.strip(" .")) == bool(raw.strip(" ,"))


# ── AC-5 · the template routes, by what was SAID ────────────────────────────


def test_keywords_match_the_anchor_text_not_the_section():
    """AC-5 — the blocker. `visual_trigger_keywords` are spoken phrases.

    Reading "has keywords" as "is a visual sink" filed wound photos under
    Past Medical History in half the shipped templates.
    """
    from app.modules.note_gen.service import get_template

    # Said "wound" → plastic surgery's wound_assessment declares it.
    assert _template_section_for_anchor_text(
        get_template("plastic_surgery"), WOUND_TALK
    ) == "wound_assessment"

    # The exact regression: family medicine's past_medical_history declares
    # keywords, but nothing about a wound matches, so it is NOT selected.
    assert _template_section_for_anchor_text(
        get_template("family_medicine"), WOUND_TALK
    ) is None

    # …and it IS selected when the physician actually says one of its phrases.
    assert _template_section_for_anchor_text(
        get_template("family_medicine"), "let's go over your family history"
    ) == "past_medical_history"


def test_template_routing_beats_the_legacy_tuple():
    """AC-5 — with a matching keyword, the template's own section wins over
    both the built-in tuple and the status fallback."""
    note = _custom_note()
    template = _keyed_template()

    assert _find_target_section(
        note, "seg_x", template, "harvesting from the donor site"
    ).id == "donor_site"
    # No keyword match → falls past the template tier to the status tier.
    assert _find_target_section(
        note, "seg_x", template, "how are you feeling today"
    ).id == "lipo_360_technique"


# ── AC-6 · the recorded defect, and the one review found ────────────────────


def test_placement_equals_prediction_for_every_caption():
    """AC-6 — THE recorded defect, now a passing test.

    Two last-tier captions were both PREDICTED into the first pending_video
    section, then merge flipped it to populated and filed the second one
    elsewhere — captured under one section's guidance, filed under another.
    """
    note = _custom_note()
    template = _keyless_template()
    captions = [
        _caption(frame_id="f1", anchor="seg_a"),
        _caption(frame_id="f2", anchor="seg_b"),
    ]

    predicted = {
        c.frame_id: _find_target_section(note, c.audio_anchor_id, template).id
        for c in captions
    }

    merge_visual_citations(note, captions, template)

    placed = {
        claim.source_id: section.id
        for section in note.sections
        for claim in section.claims
        if claim.source_type == "visual"
    }
    assert placed == predicted


def test_capture_and_merge_route_through_the_same_tier():
    """AC-6 (the one review found) — capture-time prediction was omitting
    `template`, so it routed on the built-in tuple while the merge routed on
    the template's keywords. A frame aimed at one section's guidance was filed
    under another — a WIDER divergence than the one TE-4 set out to close.

    Asserted end-to-end: the section the focus block names must be the section
    the merge actually files the claim into.
    """
    note = Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery",
        sections=[
            NoteSection(id="physical_exam", title="Physical exam",
                        status="pending_video", claims=[]),
            NoteSection(id="donor_site", title="Donor site",
                        status="pending_video", claims=[]),
        ],
    )
    template = Template(
        key="c", display_name="C",
        sections=[
            TemplateSection(id="physical_exam", title="Physical exam",
                            description="General exam findings."),
            TemplateSection(id="donor_site", title="Donor site",
                            description="Donor site appearance.",
                            visual_trigger_keywords=["donor site"]),
        ],
    )
    said = "now looking at the donor site"

    block = _section_focus_block(template, note, "seg_a", anchor_text=said)
    assert block is not None
    assert "Donor site" in block, "capture must be aimed at the keyed section"

    merge_visual_citations(
        note, [_caption(anchor="seg_a")], template, {"seg_a": said}
    )

    placed = next(
        s.id for s in note.sections
        for c in s.claims if c.source_type == "visual"
    )
    assert placed == "donor_site", (
        "aimed at donor_site but filed under physical_exam — capture and "
        "merge routed through different tiers"
    )


# ── AC-7 · the approval gate is untouched ───────────────────────────────────


def test_conflicts_still_block_approval():
    """AC-7 — `is_unresolved_conflict_claim` keys off `source_type == "visual"`
    and the `conflict_` id prefix, NOT the wording. TE-4 reformats wording."""
    from app.modules.note_gen.service import is_unresolved_conflict_claim

    note = _note_with_anchor()
    merge_visual_citations(
        note,
        [_caption(description="The image shows erythema", status="CONFLICTS")],
        _keyed_template(),
    )

    claim = note.get_section("wound_assessment").claims[-1]
    assert is_unresolved_conflict_claim(claim) is True
    assert claim.text.startswith("CONFLICT: ")


def test_conflicts_do_not_mark_a_section_populated():
    """A conflict is an open question, not a satisfied section."""
    note = _custom_note()
    merge_visual_citations(
        note, [_caption(anchor="seg_a", status="CONFLICTS")], _keyless_template()
    )
    assert note.sections[0].status != "populated"
