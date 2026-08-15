"""VIS-01/02/03 — cadence frames routed by content, not by concurrent speech.

Measured on dev before this change (session 01ce3561, bunion clip)::

    Captioning complete: total=182 captioned=2 discarded=180 failed=0
    Stage 2 complete:    frames=182 clips=0 enriches=0 conflicts=0

The model read every frame correctly — its own discard reasons say so
("a computer screen displaying an X-ray"). The frames were discarded because
SECTION FOCUS aimed them at a section chosen from the nearest SPOKEN segment,
then told the model to report low confidence if that section's content was not
visible. Cadence sampling exists to catch what the audio does not mention, so
aiming those frames by the audio guaranteed the mismatch.

These tests pin the three halves of the fix: deriving provenance, not aiming
cadence frames, and routing their captions by content.

**Widened after session f3a8e35d** (bunion post-op, ortho template, full 2m25s
encounter, 123 frames, 30 visual claims). Content routing originally applied to
cadence captions only; trigger captions were left on the anchor because "the
spoken phrase genuinely indicates what is on screen". On a real full-length
visit it does not — 11 of the 30 claims were misfiled, three radiographs among
them landing in `plan`. Provenance still decides whether a frame is AIMED at
capture time (VIS-02, unchanged); it no longer decides how the finished caption
is FILED.
"""

from __future__ import annotations

from typing import Optional

import pytest

from app.core.types import (
    FrameCaption,
    Note,
    NoteClaim,
    NoteSection,
    Template,
    TemplateSection,
    TranscriptSegment,
)

# `frame_window_clinic_ms` default. Asserting against the configured value
# rather than a literal keeps this honest if the default moves.
from app.modules.config.appconfig_client import get_config
from app.modules.vision.service import (
    _section_for_caption_text,
    frame_provenance,
    merge_visual_citations,
)


def _window_ms() -> int:
    return get_config().pipeline.frame_window_clinic_ms


def _trigger(start_ms: int, end_ms: int, ttype: str = "live_imaging_review"):
    return TranscriptSegment(
        id=f"seg_{start_ms}",
        start_ms=start_ms,
        end_ms=end_ms,
        text="I'm pulling up your X-rays now.",
        is_visual_trigger=True,
        trigger_type=ttype,
    )


# A template shaped like the real ortho/plastics ones: physical_exam BEFORE
# imaging_review, and a non-visual section that also declares keywords.
_TEMPLATE = Template(
    key="ortho",
    display_name="Ortho",
    sections=[
        TemplateSection(id="hpi", title="HPI", visual_trigger_keywords=[]),
        TemplateSection(
            id="physical_exam",
            title="Physical Examination",
            visual_trigger_keywords=["range of motion", "palpation"],
            description="Findings observed on examination, with laterality.",
        ),
        TemplateSection(
            id="imaging_review",
            title="Imaging Review",
            visual_trigger_keywords=["x-ray", "radiograph", "imaging study"],
            description="Imaging findings as literally described on screen.",
        ),
        TemplateSection(
            id="plan",
            title="Plan",
            # A non-visual section that nonetheless declares a keyword which
            # could appear in a caption. Must never receive visual evidence.
            visual_trigger_keywords=["x-ray"],
        ),
    ],
)


def _note() -> Note:
    return Note(
        session_id="s1",
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=1.0,
        sections=[
            NoteSection(
                id="hpi",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c1",
                        text="Pain for a year.",
                        source_type="transcript",
                        source_id="seg_0",
                        source_quote="",
                    )
                ],
            ),
            NoteSection(id="physical_exam", status="populated", claims=[]),
            NoteSection(id="imaging_review", status="populated", claims=[]),
            NoteSection(id="plan", status="populated", claims=[]),
        ],
    )


def _caption(
    description: str, timestamp_ms: int, anchor_id: str = "seg_0"
) -> FrameCaption:
    return FrameCaption(
        frame_id=f"frame_{timestamp_ms:05d}",
        session_id="s1",
        timestamp_ms=timestamp_ms,
        audio_anchor_id=anchor_id,
        provider_used="gemini",
        visual_description=description,
        confidence="high",
        integration_status="ENRICHES",
    )


class TestProvenance:
    """VIS-01 / AC-1, AC-2."""

    def test_provenance_inside_a_trigger_window_is_trigger(self):
        segs = [_trigger(50_000, 55_000)]
        assert frame_provenance(segs, 52_000) == "trigger"

    def test_provenance_outside_every_window_is_cadence(self):
        segs = [_trigger(50_000, 55_000)]
        far = 55_000 + _window_ms() + 1_000
        assert frame_provenance(segs, far) == "cadence"

    def test_window_padding_is_honoured_on_both_edges(self):
        segs = [_trigger(50_000, 55_000)]
        w = _window_ms()
        assert frame_provenance(segs, 50_000 - w) == "trigger"
        assert frame_provenance(segs, 55_000 + w) == "trigger"
        assert frame_provenance(segs, 50_000 - w - 1) == "cadence"

    def test_cadence_point_landing_inside_window_counts_as_trigger(self):
        """Correct by definition — it IS in that window."""
        segs = [_trigger(58_000, 62_000)]
        # A 5s cadence point at 60000 that happens to fall in a trigger window.
        assert frame_provenance(segs, 60_000) == "trigger"

    def test_no_triggers_means_everything_is_cadence(self):
        assert frame_provenance([], 60_000) == "cadence"


class TestContentRouting:
    """VIS-03 / AC-4, AC-5."""

    def test_caption_naming_an_xray_routes_to_imaging(self):
        section = _section_for_caption_text(
            _note(), _TEMPLATE, "A computer screen displaying an X-ray of the foot."
        )
        assert section is not None and section.id == "imaging_review"

    def test_never_routes_to_a_non_visual_section(self):
        """`plan` declares "x-ray" too; it must never receive visual evidence."""
        note = _note()
        # Remove imaging_review so the only keyword match left is `plan`.
        note.sections = [s for s in note.sections if s.id != "imaging_review"]
        assert _section_for_caption_text(note, _TEMPLATE, "an X-ray is visible") is None

    def test_no_match_returns_none_so_the_caller_falls_back(self):
        assert (
            _section_for_caption_text(_note(), _TEMPLATE, "A door and a chair.")
            is None
        )

    def test_no_template_returns_none(self):
        assert _section_for_caption_text(_note(), None, "an X-ray") is None


class TestMergeRouting:
    """VIS-03 end-to-end through the merge / AC-4, AC-6."""

    def _merge(self, caption: FrameCaption, trigger_segments: Optional[list]):
        note = _note()
        return merge_visual_citations(
            note,
            [caption],
            _TEMPLATE,
            {"seg_0": "I've had pain for about a year."},
            trigger_segments=trigger_segments,
        )

    def _section_with_frame_claim(self, note: Note) -> Optional[str]:
        for section in note.sections:
            for claim in section.claims:
                if claim.source_type == "visual":
                    return section.id
        return None

    def test_cadence_xray_caption_lands_in_imaging_not_hpi(self):
        """The regression.

        The audio anchor `seg_0` is cited by the HPI claim, so anchor routing
        files this under HPI. The frame shows an X-ray. Content wins.
        """
        # 200s: far outside the 50-55s trigger window -> cadence.
        caption = _caption("A computer screen displaying an X-ray.", 200_000)
        merged = self._merge(caption, [_trigger(50_000, 55_000)])
        assert self._section_with_frame_claim(merged) == "imaging_review"

    def test_trigger_frame_also_routes_by_content(self):
        """Supersedes the original AC-6 ("trigger frames are unchanged").

        AC-6 rested on VIS-02's reasoning that for a trigger frame "the spoken
        phrase genuinely indicates what is on screen". A full-length encounter
        disproved it — session f3a8e35d misfiled 11 of 30 visual claims,
        including three radiographs filed under `plan`, because the surgeon
        narrates one thing while the camera shows another.

        Same input as the old test; the expectation is inverted. The anchor
        `seg_0` is cited in HPI, but the frame shows an X-ray, so it belongs in
        imaging_review whether or not it sits inside a trigger window.
        """
        caption = _caption("A computer screen displaying an X-ray.", 52_000)
        merged = self._merge(caption, [_trigger(50_000, 55_000)])
        assert self._section_with_frame_claim(merged) == "imaging_review"

    def test_trigger_frame_with_no_content_match_still_falls_back_to_anchor(self):
        """Content routing only overrides when it actually recognises something.

        A caption the keywords do not match must not be stranded — it keeps
        the anchor's destination, exactly as before.
        """
        caption = _caption("A door and an empty chair.", 52_000)
        merged = self._merge(caption, [_trigger(50_000, 55_000)])
        assert self._section_with_frame_claim(merged) == "hpi"

    def test_a_trigger_frame_never_content_routes_into_a_non_visual_section(self):
        """`plan` declares "x-ray" as a keyword; it must still never receive one.

        This is the `plan` half of the production bug: three radiographs were
        filed there. Content routing cannot reproduce it because
        `_section_for_caption_text` only considers visual sinks — but the
        guarantee is worth pinning at the merge level, not just the unit level.
        """
        note = _note()
        note.sections = [s for s in note.sections if s.id != "imaging_review"]
        merged = merge_visual_citations(
            note,
            [_caption("A computer screen displaying an X-ray.", 52_000)],
            _TEMPLATE,
            {"seg_0": "I've had pain for about a year."},
            trigger_segments=[_trigger(50_000, 55_000)],
        )
        assert self._section_with_frame_claim(merged) != "plan"

    def test_without_trigger_segments_behaviour_is_unchanged(self):
        """Every non-Stage-2 caller passes None and must be byte-identical."""
        caption = _caption("A computer screen displaying an X-ray.", 200_000)
        merged = self._merge(caption, None)
        assert self._section_with_frame_claim(merged) == "hpi"

    def test_cadence_caption_with_no_content_match_falls_back_to_anchor(self):
        caption = _caption("A door and an empty chair.", 200_000)
        merged = self._merge(caption, [_trigger(50_000, 55_000)])
        assert self._section_with_frame_claim(merged) == "hpi"


class TestSectionFocusSuppression:
    """VIS-02 / AC-3 — cadence frames are not aimed at a section."""

    @pytest.mark.asyncio
    async def test_cadence_frame_gets_no_section_focus_and_trigger_frame_does(
        self, monkeypatch
    ):
        """Assert on the SYSTEM PROMPT each frame is captioned with.

        The bug lived in the prompt, so that is what this pins: the cadence
        frame must not carry the SECTION FOCUS block (and therefore not its
        "report confidence low if irrelevant" instruction), while the trigger
        frame must still carry it.
        """
        from app.modules.vision import service as vs

        seen: dict[int, Optional[str]] = {}

        async def _fake_dispatch(_provider, item, anchor, system_prompt):
            seen[item.timestamp_ms] = system_prompt
            return _caption("desc", item.timestamp_ms, anchor.id)

        class _FakeProvider:
            pass

        class _FakeRegistry:
            def get_vision_provider_for_kind_with_fallback(self, _kind):
                return _FakeProvider()

        monkeypatch.setattr(vs, "_dispatch_caption", _fake_dispatch)
        monkeypatch.setattr(vs, "get_registry", lambda: _FakeRegistry())
        monkeypatch.setattr(
            vs, "try_record_provider_usage", _noop_async, raising=False
        )

        triggers = [_trigger(50_000, 55_000)]
        frames = [
            _masked_frame(52_000),   # inside the window  -> trigger
            _masked_frame(200_000),  # far outside        -> cadence
        ]

        await vs.caption_visual_evidence(
            frames,
            triggers,
            anchor_segments=triggers,
            template=_TEMPLATE,
            note=_note(),
        )

        assert "SECTION FOCUS" in (seen[52_000] or ""), (
            "trigger frame lost its section aim — that is a regression, the "
            "spoken phrase genuinely indicates what is on screen there"
        )
        assert "SECTION FOCUS" not in (seen[200_000] or ""), (
            "cadence frame still aimed at a section; it will keep being told "
            "to report low confidence when the audio's topic is not visible"
        )


async def _noop_async(*_args, **_kwargs):
    return None


def _masked_frame(timestamp_ms: int):
    from app.core.types import MaskedFrame

    return MaskedFrame(
        frame_id=f"frame_{timestamp_ms:05d}",
        session_id="s1",
        timestamp_ms=timestamp_ms,
        s3_key=f"frames/s1/{timestamp_ms}.jpg",
        masking_confirmed=True,
    )


class TestStage2RouteWiring:
    """The real route must thread `trigger_segments` into the merge.

    Everything above tests `merge_visual_citations` directly. That leaves the
    wiring untested: if `api/v1/vision.py` forgot to pass `trigger_segments`,
    the merge would silently fall back to anchor routing and every test above
    would still pass while production stayed broken. This drives
    `run_stage2_vision` with the REAL merge and asserts on where the claim
    landed.
    """

    @pytest.mark.asyncio
    async def test_cadence_caption_reaches_imaging_through_the_real_route(
        self, monkeypatch
    ):
        import uuid
        from types import SimpleNamespace

        from app.api.v1 import vision as route
        from app.core.types import MaskedFrame, Transcript

        # A trigger at 50-55s, and a frame at 200s — far outside it, so the
        # route must classify the frame as cadence.
        transcript = Transcript(
            session_id="s1",
            provider_used="assemblyai",
            segments=[
                TranscriptSegment(
                    id="seg_0",
                    start_ms=0,
                    end_ms=5_000,
                    text="I've had pain for about a year.",
                ),
                _trigger(50_000, 55_000),
            ],
        )

        class _Result:
            def __init__(self, value):
                self._value = value

            def scalar_one_or_none(self):
                return self._value

        rows = [
            _Result(SimpleNamespace(transcript_json=transcript.model_dump_json())),
            _Result(
                SimpleNamespace(
                    template_key=None,
                    custom_template_id=None,
                    clinician_id=None,
                )
            ),
        ]

        class _DB:
            async def execute(self, *_a, **_kw):
                return rows.pop(0)

        async def _async(value):
            return value

        async def _noop(*_a, **_kw):
            return None

        # The caption the model would return for an UN-AIMED X-ray frame.
        # Its production counterpart was discarded as low-confidence purely
        # because SECTION FOCUS pointed it at the physical exam.
        xray_caption = _caption(
            "A computer screen displaying an X-ray of the right foot.", 200_000
        )

        note_holder: dict = {}

        async def _capture_version(_sid, note, *_a, **_kw):
            note_holder["note"] = note

        # VIS-03 only engages when the template engine is ON — with no
        # template there is nothing to match a caption against, and the merge
        # takes its legacy anchor-routing path. Dev has this enabled (the
        # production discard reasons name specific sections, which only
        # `_section_focus_block` produces, and that needs a template).
        cfg = get_config().model_copy(deep=True)
        cfg.feature_flags.template_engine_enabled = True
        monkeypatch.setattr(route, "get_config", lambda: cfg)
        monkeypatch.setattr(route, "get_latest_note", lambda *_a, **_k: _async(_note()))
        monkeypatch.setattr(
            route, "resolve_session_template", lambda *_a, **_k: _async(_TEMPLATE)
        )
        monkeypatch.setattr(
            route,
            "caption_visual_evidence",
            lambda **_kw: _async([xray_caption]),
        )
        monkeypatch.setattr(
            route,
            "retrieve_all_masked_frames",
            lambda *_a, **_k: _async(
                [
                    MaskedFrame(
                        frame_id="frame_200000",
                        session_id="s1",
                        timestamp_ms=200_000,
                        s3_key="frames/s1/200000.jpg",
                        masking_confirmed=True,
                    )
                ]
            ),
        )
        monkeypatch.setattr(
            route, "retrieve_clips_for_triggers", lambda *_a, **_k: _async([])
        )
        monkeypatch.setattr(route, "assemble_prompt", lambda *_a, **_k: _async("P"))
        monkeypatch.setattr(
            route, "reconcile_captions", lambda *_a, **_k: _async([xray_caption])
        )
        monkeypatch.setattr(route, "create_note_version", _capture_version)
        monkeypatch.setattr(route, "write_audit", _noop)
        monkeypatch.setattr(route, "record_clip_metrics", _noop)
        monkeypatch.setattr(route, "has_unresolved_conflicts", lambda _c: False)
        # NOT patched: merge_visual_citations. That is the code under test.

        await route.run_stage2_vision(uuid.uuid4(), _DB())

        merged = note_holder.get("note")
        assert merged is not None, "Stage 2 never produced a note version"
        landed = [
            s.id
            for s in merged.sections
            for c in s.claims
            if c.source_type == "visual"
        ]
        assert landed == ["imaging_review"], (
            f"cadence X-ray caption landed in {landed or 'nowhere'}; the route "
            "is not threading trigger_segments into the merge, so it fell back "
            "to routing by the audio anchor"
        )


class TestRoutingHygiene:
    """VIS-04 (#746) and VIS-05 (#747)."""

    def test_tier3_fallback_is_independent_of_template_section_order(self):
        """VIS-04 — two templates declaring the same visual sections in a
        different ORDER must route an unroutable frame identically.

        The property is template-independence, not which section wins.
        Previously the loop ran over `note.sections`, so template layout
        silently decided the outcome.
        """
        from app.modules.vision.service import _find_target_section

        def _note_with(order: list[str]) -> Note:
            return Note(
                session_id="s1", stage=1, version=1, provider_used="p",
                specialty="x", completeness_score=1.0,
                sections=[
                    NoteSection(id=i, status="populated", claims=[]) for i in order
                ],
            )

        exam_first = _find_target_section(
            _note_with(["physical_exam", "imaging_review"]), "nope"
        )
        imaging_first = _find_target_section(
            _note_with(["imaging_review", "physical_exam"]), "nope"
        )
        assert exam_first is not None and imaging_first is not None
        assert exam_first.id == imaging_first.id, (
            "tier-3 outcome still depends on template section order"
        )

    def test_anchor_is_refused_when_the_nearest_speech_is_far_away(self):
        """VIS-05 — an arbitrary anchor minutes away is worse than none."""
        from app.modules.vision.service import _find_anchor_segment

        segs = [_trigger(0, 5_000)]
        near = _find_anchor_segment(3_000, segs)
        far = _find_anchor_segment(10 * 60 * 1_000, segs)
        assert near is not None, "a frame beside the speech must still anchor"
        assert far is None, "a frame ten minutes from any speech must not anchor"

    def test_empty_segment_pool_returns_none(self):
        from app.modules.vision.service import _find_anchor_segment

        assert _find_anchor_segment(1_000, []) is None

    @pytest.mark.asyncio
    async def test_a_distant_cadence_frame_is_still_captioned_not_dropped(
        self, monkeypatch
    ):
        """The regression VIS-05 nearly introduced.

        Bounding the anchor makes a cadence frame in a silent stretch legally
        anchorless — and the frame path DROPS anchorless frames. That would
        delete exactly the frames VIS-02/03 exist to rescue. A cadence frame
        no longer needs speech, so it must earn a synthesized anchor instead.
        """
        from app.modules.vision import service as vs

        captioned: list[int] = []

        async def _fake_dispatch(_provider, item, anchor, _system_prompt):
            captioned.append(item.timestamp_ms)
            return _caption("desc", item.timestamp_ms, anchor.id)

        class _FakeRegistry:
            def get_vision_provider_for_kind_with_fallback(self, _kind):
                return object()

        monkeypatch.setattr(vs, "_dispatch_caption", _fake_dispatch)
        monkeypatch.setattr(vs, "get_registry", lambda: _FakeRegistry())
        monkeypatch.setattr(
            vs, "try_record_provider_usage", _noop_async, raising=False
        )

        triggers = [_trigger(0, 5_000)]
        # 10 minutes from the only speech in the transcript.
        far_frame = _masked_frame(10 * 60 * 1_000)

        await vs.caption_visual_evidence(
            [far_frame], triggers, anchor_segments=triggers
        )

        assert captioned == [10 * 60 * 1_000], (
            "a distant cadence frame was dropped instead of captioned with a "
            "synthesized anchor"
        )
