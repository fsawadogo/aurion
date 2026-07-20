"""TE-4 — the merge routes by the template and builds the claim.

TE-3 aimed the CAPTURE. The merge was still `text=caption.visual_description`
verbatim into a section chosen from a hardcoded id tuple, so a frame's
contribution to the note was whatever prose the model happened to emit.

Three things land here:

  * **The recorded defect.** Tier 3 of `_find_target_section` reads
    `section.status`, and the merge flips `pending_video` -> `populated` as it
    goes — so routing inside the apply loop made placement disagree with
    TE-3's capture-time prediction. Routing now happens against the pristine
    note, before any mutation, which makes them identical by construction.
  * **The clutter TE-3 created.** Its SECTION FOCUS block instructs the model
    to "say so" when nothing relevant is visible — so aiming the capture
    GUARANTEES such captions exist. Pasting them into the chart would be new
    clutter produced by the fix for clutter.
  * **The image-caption voice.** "The image shows a healing incision"
    describes the medium; "A healing incision" is a clinical observation.

All of it is gated: `template is None` (engine off) reproduces pre-TE-4 output
byte for byte.
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
    _is_no_finding_caption,
    merge_visual_citations,
)


def _caption(
    frame_id: str = "f1",
    description: str = "A healing incision with clean margins",
    status: str = "ENRICHES",
    anchor: str = "seg_014",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="s1",
        timestamp_ms=1000,
        audio_anchor_id=anchor,
        provider_used="anthropic",
        visual_description=description,
        confidence="high",
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
    """A custom template's sections — none in the legacy visual tuple, both
    pending_video, so every caption lands in tier 3. This is the shape that
    exposed the prediction/placement divergence."""
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


def _custom_template() -> Template:
    return Template(
        key="custom", display_name="Custom",
        sections=[
            TemplateSection(id="lipo_360_technique", title="Technique",
                            description="Operative technique as observed.",
                            visual_trigger_keywords=["cannula", "technique"]),
            TemplateSection(id="donor_site", title="Donor site",
                            description="Donor site appearance."),
        ],
    )


# ── AC-1 · the claim is built, not pasted ───────────────────────────────────


def test_claim_text_is_constructed_but_traceability_is_unchanged():
    """AC-1 — the text changes; the citation does not."""
    note = _note_with_anchor()
    caption = _caption(description="The image shows a healing incision")

    merge_visual_citations(note, [caption], _custom_template())

    claim = note.get_section("wound_assessment").claims[-1]
    assert claim.text != caption.visual_description
    # …and everything traceability depends on survives verbatim.
    assert claim.source_type == "visual"
    assert claim.source_id == "f1"
    assert claim.id == "vclaim_f1"
    assert "f1" in claim.source_quote


# ── AC-2 · flag OFF is byte-identical ───────────────────────────────────────


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
    """AC-2 — `template=None` must produce the byte-for-byte claim the
    pre-TE-4 code produced.

    Asserted against the OLD implementation transcribed literally, not against
    a belief about it: the formatter initially ran unconditionally, which
    silently changed every note's wording while the engine was nominally dark.
    The epic's byte-identical promise covers merged OUTPUT, not just prompts.
    """
    caption = _caption(description=description, status=status)

    note = _note_with_anchor()
    merge_visual_citations(note, [caption], None)
    got = note.get_section("wound_assessment").claims[-1]

    # Verbatim transcription of the pre-TE-4 construction.
    if status == "ENRICHES":
        expected_id = f"vclaim_{caption.frame_id}"
        expected_text = caption.visual_description
    else:
        expected_id = f"conflict_{caption.frame_id}"
        expected_text = (
            "CONFLICT: Visual observation differs from audio — "
            f"{caption.visual_description}"
        )

    assert got.id == expected_id
    assert got.text == expected_text
    assert got.source_type == "visual"
    assert got.source_id == caption.frame_id


def test_engine_off_keeps_the_legacy_section_tuple():
    """AC-2 — routing with no template still uses the hardcoded visual
    sections, so notes built without the engine land exactly where they did."""
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


# ── AC-3 · the clutter TE-3 guarantees ──────────────────────────────────────


@pytest.mark.parametrize(
    "description",
    [
        "Nothing relevant to the wound assessment is visible in this frame.",
        "No relevant findings are visible.",
        "The patient's arm is not visible in this image.",
        "Unable to assess the wound from this angle.",
        "Nothing of note is visible.",
    ],
)
def test_no_finding_captions_never_become_claims(description):
    """AC-3 — TE-3's prompt says "if nothing relevant is visible, say so", so
    these captions are a GUARANTEED product of aiming the capture. They assert
    the absence of evidence; a note claim asserts a finding."""
    note = _note_with_anchor()
    before = len(note.get_section("wound_assessment").claims)

    merge_visual_citations(note, [_caption(description=description)],
                           _custom_template())

    assert len(note.get_section("wound_assessment").claims) == before


def test_no_finding_caption_does_not_mark_a_section_populated():
    """AC-3 — and it must not overstate completeness either. Flipping
    pending_video -> populated on a caption that found nothing would inflate
    `template_section_completeness` with an empty section."""
    note = _custom_note()

    merge_visual_citations(
        note, [_caption(anchor="seg_x", description="Nothing relevant is visible.")],
        _custom_template(),
    )

    assert note.sections[0].claims == []
    # Falls through to the end-of-merge sweep, like any unfilled section.
    assert note.sections[0].status == "not_captured"


def test_a_conflict_is_reported_even_when_the_frame_shows_nothing():
    """The disagreement with the audio IS the finding — dropping it would
    silently remove a claim the approval gate depends on."""
    note = _note_with_anchor()

    merge_visual_citations(
        note,
        [_caption(description="Nothing relevant is visible.", status="CONFLICTS")],
        _custom_template(),
    )

    claim = note.get_section("wound_assessment").claims[-1]
    assert claim.id == "conflict_f1"


# ── AC-4 · the image-caption voice ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("The image shows a healing incision", "A healing incision."),
        ("This frame shows mild erythema", "Mild erythema."),
        ("In this image, the wound bed is pink", "The wound bed is pink."),
        ("The photo depicts a clean dressing", "A clean dressing."),
        ("Visible in this frame is a surgical drain",
         "A surgical drain."),
        ("The video shows the knee flexing", "The knee flexing."),
        # No opener — content preserved, punctuation normalised.
        ("Mild swelling at the lateral border", "Mild swelling at the lateral border."),
        # Already well-formed — untouched.
        ("A healing incision with clean margins.",
         "A healing incision with clean margins."),
    ],
)
def test_image_meta_openers_are_stripped(raw: str, expected: str):
    """AC-4 — "The image shows X" describes the MEDIUM. The note wants X."""
    assert _format_visual_claim_text(raw) == expected


def test_formatter_only_removes_never_adds():
    """AC-4 (safety) — the formatter cannot introduce an inference because it
    cannot introduce words. Every word of the output must appear in the input.

    This is the property that lets a deterministic formatter sit between a
    caption and the chart without a second safety screen.
    """
    raw = "The image shows a 3cm laceration with surrounding erythema"
    out = _format_visual_claim_text(raw)

    src = raw.lower()
    for word in out.rstrip(".").lower().split():
        assert word in src, f"formatter invented {word!r}"


def test_a_caption_that_is_only_an_opener_is_not_emptied():
    """Degradation — stripping must never produce an empty claim."""
    assert _format_visual_claim_text("The image shows") == "The image shows"


def test_no_finding_detector_does_not_fire_on_real_findings():
    """The drop must be narrow. A real observation that merely contains
    "visible" or "no" must survive."""
    for text in (
        "A visible healing ridge along the incision.",
        "No erythema at the wound margins.",
        "The drain is visible at the lateral border.",
        "Sutures intact with no dehiscence.",
    ):
        assert _is_no_finding_caption(text) is False, text


# ── AC-5 · the template routes ──────────────────────────────────────────────


def test_template_visual_sections_beat_the_legacy_tuple():
    """AC-5 — a custom template's own visual section wins.

    Deliberately constructed so the two answers DIFFER. `donor_site` is the
    section carrying the keywords and it is SECOND, while tier 3 would pick
    the first pending_video section. An earlier draft of this test put the
    keywords on the first section, so both paths returned it and the assertion
    could not tell template routing from the legacy fallback.
    """
    note = _custom_note()
    template = Template(
        key="custom", display_name="Custom",
        sections=[
            TemplateSection(id="lipo_360_technique", title="Technique"),
            TemplateSection(id="donor_site", title="Donor site",
                            visual_trigger_keywords=["donor", "graft"]),
        ],
    )

    # With the template: its own declaration selects the SECOND section.
    assert _find_target_section(note, "seg_none", template).id == "donor_site"
    # Without it: no custom id is in the legacy tuple, so tier 3 takes the
    # FIRST pending_video section instead.
    assert _find_target_section(note, "seg_none", None).id == "lipo_360_technique"


def test_measurement_sections_also_count_as_visual():
    """`measurement_output_expected` marks a section that receives on-device
    measurements — also visual by nature."""
    note = Note(
        session_id="s1", stage=1, version=1, provider_used="anthropic",
        specialty="ortho",
        sections=[
            NoteSection(id="hpi", title="HPI", status="populated", claims=[]),
            NoteSection(id="rom_check", title="ROM", status="populated", claims=[]),
        ],
    )
    template = Template(
        key="c", display_name="C",
        sections=[
            TemplateSection(id="hpi", title="HPI"),
            TemplateSection(id="rom_check", title="ROM",
                            measurement_output_expected=True),
        ],
    )
    assert _find_target_section(note, "seg_none", template).id == "rom_check"


# ── AC-6 · the recorded defect ──────────────────────────────────────────────


def _tier3_template() -> Template:
    """A template with NO visual markers, so routing falls past tier 2.

    Load-bearing for the two tests below: the divergence is a TIER 3
    phenomenon — tier 3 is the only tier that reads `status`, which the merge
    mutates. A template that marks a visual section sends these captions to
    tier 2, which is status-independent, and the bug becomes unreachable. An
    earlier draft of these tests did exactly that and would have passed
    against the unfixed code.
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


def test_placement_equals_prediction_for_every_caption():
    """AC-6 — THE recorded defect, now a passing test.

    TE-3's review pinned this as a known divergence: two tier-3 captions were
    both PREDICTED into the first pending_video section, then merge flipped
    that section to populated and filed the second one elsewhere. So a frame
    was captured under one section's guidance and filed under another.

    Prediction runs on the note as loaded; the merge must agree with it.
    """
    note = _custom_note()
    template = _tier3_template()

    captions = [
        _caption(frame_id="f1", anchor="seg_a"),
        _caption(frame_id="f2", anchor="seg_b"),
    ]

    # What TE-3 predicted at capture time, on the note as Stage 1 left it.
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

    assert placed == predicted, (
        "a frame was captured under one section's guidance and filed under "
        "another — the divergence TE-4 exists to close"
    )


def test_repeats_do_not_shift_anyone_elses_routing():
    """AC-6 (second cause) — REPEATS were dropped *between* prediction and
    placement, so they shifted which caption consumed which tier-3 section.
    Routing now drops them before anything is placed."""
    note = _custom_note()
    template = _tier3_template()

    captions = [
        _caption(frame_id="f0", anchor="seg_r", status="REPEATS"),
        _caption(frame_id="f1", anchor="seg_a"),
    ]
    predicted = _find_target_section(note, "seg_a", template).id

    merge_visual_citations(note, captions, template)

    placed = [
        (claim.source_id, section.id)
        for section in note.sections
        for claim in section.claims
        if claim.source_type == "visual"
    ]
    assert placed == [("f1", predicted)]


# ── AC-7 · the approval gate is untouched ───────────────────────────────────


def test_conflicts_still_block_approval():
    """AC-7 — `is_unresolved_conflict_claim` keys off `source_type == "visual"`
    and the `conflict_` id prefix, NOT the wording. TE-4 reformats the wording,
    so this pins the contract it must not break."""
    from app.modules.note_gen.service import is_unresolved_conflict_claim

    note = _note_with_anchor()
    merge_visual_citations(
        note,
        [_caption(description="The image shows erythema", status="CONFLICTS")],
        _custom_template(),
    )

    claim = note.get_section("wound_assessment").claims[-1]
    assert is_unresolved_conflict_claim(claim) is True
    assert claim.text.startswith("CONFLICT: ")


def test_conflicts_do_not_mark_a_section_populated():
    """Preserved from pre-TE-4: a conflict is an open question, not a
    satisfied section."""
    note = _custom_note()

    merge_visual_citations(
        note, [_caption(anchor="seg_a", status="CONFLICTS")], _custom_template()
    )

    assert note.sections[0].status != "populated"
