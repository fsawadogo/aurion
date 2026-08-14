"""VIS-08 — the video note must cite real evidence, not pseudo-segments.

`generate_video_note` turns captions into a pseudo-transcript so the existing
note-gen engine can read them. The engine then cites the segment it read —
``vseg_003`` — which does not exist anywhere: it is an artefact of that
function. A claim carrying it is untraceable. Tap-to-source has nothing to
open, and `citation_traceability_rate` scores it as valid when it is not.

This matters most under Grounded Synthesis, where a synthesized statement is
permitted precisely BECAUSE it cites its sources (CLAUDE.md: "uncited
conclusions are forbidden in BOTH modes"). Citing a fabricated id is what that
gate exists to prevent — so dropping citations is not a way to buy interpretive
freedom, it is a way to forfeit it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.types import (
    ClaimSource,
    Note,
    NoteClaim,
    NoteSection,
    Template,
    TemplateSection,
)
from app.modules.note_gen.fusion import (
    _pseudo_transcript_from_captions,
    generate_video_note,
)

_TEMPLATE = Template(
    key="ortho",
    display_name="Ortho",
    sections=[
        TemplateSection(id="physical_exam", title="Exam", description="Findings."),
        TemplateSection(id="imaging_review", title="Imaging", description="Imaging."),
    ],
)


def _caption(frame_id: str, ts: int, desc: str, confidence: str = "high"):
    return SimpleNamespace(
        frame_id=frame_id,
        timestamp_ms=ts,
        duration_ms=0,
        visual_description=desc,
        confidence=confidence,
    )


class TestPseudoTranscriptAnchors:
    def test_anchor_map_pairs_each_segment_with_its_evidence(self):
        caps = [
            _caption("frame_00100", 100, "A foot."),
            _caption("frame_00200", 200, "An X-ray on a monitor."),
        ]
        pseudo, anchors = _pseudo_transcript_from_captions("s1", caps)

        assert [s.id for s in pseudo.segments] == ["vseg_000", "vseg_001"]
        assert anchors == {
            "vseg_000": "frame_00100",
            "vseg_001": "frame_00200",
        }

    def test_empty_captions_are_skipped_without_shifting_the_map(self):
        """The map must agree with the SKIP logic, not just the sort order.

        An empty description is dropped from the transcript; if the anchor map
        were rebuilt separately by index it would silently pair every later
        segment with the wrong frame.
        """
        caps = [
            _caption("frame_00100", 100, "A foot."),
            _caption("frame_00150", 150, "   "),  # dropped
            _caption("frame_00200", 200, "An X-ray."),
        ]
        pseudo, anchors = _pseudo_transcript_from_captions("s1", caps)

        assert len(pseudo.segments) == 2
        for seg in pseudo.segments:
            assert seg.text.strip()
        # vseg_002 is the X-ray (enumerate counts the skipped one), and it must
        # map to frame_00200 — not to the dropped frame.
        assert anchors[pseudo.segments[1].id] == "frame_00200"

    def test_captions_are_ordered_by_timestamp(self):
        caps = [
            _caption("frame_00200", 200, "Second."),
            _caption("frame_00100", 100, "First."),
        ]
        pseudo, anchors = _pseudo_transcript_from_captions("s1", caps)
        assert anchors[pseudo.segments[0].id] == "frame_00100"


class TestReAnchoring:
    """The end-to-end property: no claim escapes citing a pseudo-segment."""

    @pytest.fixture
    def _patched(self, monkeypatch):
        def _run(note_from_engine: Note):
            from app.modules.note_gen import fusion

            class _Provider:
                async def generate_note(self, *_a, **_kw):
                    return note_from_engine

            monkeypatch.setattr(
                fusion,
                "get_registry",
                lambda: SimpleNamespace(
                    get_note_provider_with_fallback=lambda: _Provider(),
                    get_note_provider=lambda **_kw: _Provider(),
                ),
            )
            return fusion

        return _run

    @pytest.mark.asyncio
    async def test_claims_are_re_anchored_to_the_real_frame(self, _patched):
        engine_note = Note(
            session_id="s1", stage=1, version=1, provider_used="anthropic",
            specialty="ortho", completeness_score=1.0,
            sections=[
                NoteSection(
                    id="imaging_review", status="populated",
                    claims=[
                        NoteClaim(
                            id="c1",
                            text="An X-ray of the right foot is displayed.",
                            source_type="transcript",   # engine can't know better
                            source_id="vseg_001",       # the fabricated anchor
                            source_quote="",
                        )
                    ],
                )
            ],
        )
        _patched(engine_note)

        note = await generate_video_note(
            "s1",
            [],
            _TEMPLATE,
            grounded=False,
            captions=[
                _caption("frame_00100", 100, "A foot."),
                _caption("frame_00200", 200, "An X-ray on a monitor."),
            ],
        )

        claim = note.sections[0].claims[0]
        assert claim.source_id == "frame_00200", (
            "claim still cites a pseudo-segment; tap-to-source has nothing to open"
        )
        assert claim.source_type == "visual"
        assert "frame_00200" in claim.source_quote

    @pytest.mark.asyncio
    async def test_grounded_additional_sources_are_re_anchored_too(self, _patched):
        """A synthesized claim rests on several anchors; every one must resolve."""
        engine_note = Note(
            session_id="s1", stage=1, version=1, provider_used="anthropic",
            specialty="ortho", completeness_score=1.0,
            sections=[
                NoteSection(
                    id="physical_exam", status="populated",
                    claims=[
                        NoteClaim(
                            id="c1", text="Hallux valgus deformity.",
                            source_type="transcript", source_id="vseg_000",
                            source_quote="",
                            additional_sources=[ClaimSource(source_id="vseg_001")],
                        )
                    ],
                )
            ],
        )
        _patched(engine_note)

        note = await generate_video_note(
            "s1", [], _TEMPLATE, grounded=True,
            captions=[
                _caption("frame_00100", 100, "A foot."),
                _caption("frame_00200", 200, "An X-ray."),
            ],
        )

        claim = note.sections[0].claims[0]
        assert claim.source_id == "frame_00100"
        assert [s.source_id for s in claim.additional_sources] == ["frame_00200"]

    @pytest.mark.asyncio
    async def test_an_invented_citation_drops_the_claim(self, _patched):
        """A claim resting on nothing must not ship with a dangling anchor.

        If the model cites a segment that was never in the pseudo-transcript,
        there is no evidence behind the claim. Dropping is the descriptive-safe
        direction; keeping it would put an untraceable statement in a note.
        """
        engine_note = Note(
            session_id="s1", stage=1, version=1, provider_used="anthropic",
            specialty="ortho", completeness_score=1.0,
            sections=[
                NoteSection(
                    id="physical_exam", status="populated",
                    claims=[
                        NoteClaim(
                            id="c1", text="Invented finding.",
                            source_type="transcript", source_id="vseg_099",
                            source_quote="",
                        )
                    ],
                )
            ],
        )
        _patched(engine_note)

        note = await generate_video_note(
            "s1", [], _TEMPLATE, grounded=False,
            captions=[_caption("frame_00100", 100, "A foot.")],
        )

        assert note.sections[0].claims == []
        assert note.sections[0].status == "not_captured", (
            "an emptied section must not still claim to be populated — that "
            "overstates completeness"
        )

    @pytest.mark.asyncio
    async def test_no_claim_anywhere_keeps_a_pseudo_segment_id(self, _patched):
        """Belt-and-braces sweep over the whole note."""
        engine_note = Note(
            session_id="s1", stage=1, version=1, provider_used="anthropic",
            specialty="ortho", completeness_score=1.0,
            sections=[
                NoteSection(
                    id="physical_exam", status="populated",
                    claims=[
                        NoteClaim(
                            id="c1", text="A.", source_type="transcript",
                            source_id="vseg_000", source_quote="",
                        )
                    ],
                ),
                NoteSection(
                    id="imaging_review", status="populated",
                    claims=[
                        NoteClaim(
                            id="c2", text="B.", source_type="transcript",
                            source_id="vseg_001", source_quote="",
                        )
                    ],
                ),
            ],
        )
        _patched(engine_note)

        note = await generate_video_note(
            "s1", [], _TEMPLATE, grounded=False,
            captions=[
                _caption("frame_00100", 100, "A foot."),
                _caption("frame_00200", 200, "An X-ray."),
            ],
        )

        for section in note.sections:
            for claim in section.claims:
                assert not claim.source_id.startswith("vseg_"), (
                    f"{claim.source_id} is a fabricated anchor"
                )
                for extra in claim.additional_sources:
                    assert not extra.source_id.startswith("vseg_")
