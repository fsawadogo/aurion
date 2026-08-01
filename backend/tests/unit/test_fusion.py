"""Fusion B — parallel-then-merge note assembly.

Locks the two testable units: the pseudo-transcript builder (captions →
note-engine input) and the section-weighted note-vs-note merge. The merge is a
pure function, so its modality weighting and conflict-surfacing are pinned
directly. generate_video_note is covered with the provider + captioning mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.note_gen.fusion as fusion
from app.core.types import (
    FrameCaption,
    Note,
    NoteClaim,
    NoteSection,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _claim(cid: str, text: str, source: str = "transcript") -> NoteClaim:
    return NoteClaim(id=cid, text=text, source_type=source, source_id="seg_1")


def _section(sid: str, *claims: NoteClaim, status: str = "populated") -> NoteSection:
    cl = list(claims)
    return NoteSection(
        id=sid, title=sid, status=status if cl else "not_captured", claims=cl
    )


def _note(*sections: NoteSection, provider: str = "anthropic") -> Note:
    return Note(
        session_id="s1", stage=1, version=1, provider_used=provider,
        specialty="orthopedic_surgery", sections=list(sections),
    )


def _caption(ts: int, desc: str, conf: str = "high") -> FrameCaption:
    return FrameCaption(
        frame_id=f"frame_{ts}", session_id="s1", timestamp_ms=ts,
        audio_anchor_id="seg_1", provider_used="gemini", visual_description=desc,
        confidence=conf, confidence_reason="clear", conflict_flag=False,
        conflict_detail=None, integration_status="ENRICHES",
    )


# ── pseudo-transcript ────────────────────────────────────────────────────────


def test_pseudo_transcript_one_segment_per_caption_ordered() -> None:
    caps = [_caption(3000, "third"), _caption(1000, "first"), _caption(2000, "second")]
    t = fusion._pseudo_transcript_from_captions("s1", caps)
    assert [s.text for s in t.segments] == ["first", "second", "third"]
    assert [s.start_ms for s in t.segments] == [1000, 2000, 3000]
    assert t.provider_used == "vision"


def test_pseudo_transcript_skips_empty_descriptions() -> None:
    caps = [_caption(1000, "seen"), _caption(2000, "   "), _caption(3000, "")]
    t = fusion._pseudo_transcript_from_captions("s1", caps)
    assert [s.text for s in t.segments] == ["seen"]


# ── merge: modality weighting ────────────────────────────────────────────────


def test_visual_section_takes_video_note() -> None:
    audio = _note(
        _section("hpi", _claim("a1", "knee pain 3 weeks")),
        _section("physical_exam", _claim("a2", "patient reports tenderness")),
    )
    video = _note(
        _section("physical_exam", _claim("v1", "reduced knee flexion ~110 degrees", "visual")),
        provider="gemini",
    )
    merged = fusion.merge_parallel_notes(audio, video)
    ex = merged.get_section("physical_exam")
    assert ex is not None
    # Video finding is present…
    assert any("110" in c.text for c in ex.claims)
    # …and the audio exam claim is surfaced as a conflict, not dropped.
    assert any(c.id.startswith("conflict_audio_") for c in ex.claims)


def test_audio_section_takes_audio_note() -> None:
    audio = _note(_section("hpi", _claim("a1", "3-week history of knee pain")))
    video = _note(
        _section("hpi", _claim("v1", "no visible history", "visual")),
        _section("physical_exam", _claim("v2", "swelling at joint line", "visual")),
        provider="gemini",
    )
    merged = fusion.merge_parallel_notes(audio, video)
    hpi = merged.get_section("hpi")
    assert hpi is not None
    # Audio wins hpi — the video's hpi content does NOT override it.
    assert [c.id for c in hpi.claims] == ["a1"]


def test_visual_section_empty_in_video_falls_back_to_audio() -> None:
    audio = _note(_section("physical_exam", _claim("a1", "tender to palpation")))
    video = _note(_section("physical_exam", status="not_captured"), provider="gemini")
    merged = fusion.merge_parallel_notes(audio, video)
    ex = merged.get_section("physical_exam")
    assert ex is not None and [c.id for c in ex.claims] == ["a1"]


def test_video_only_section_is_appended() -> None:
    audio = _note(_section("hpi", _claim("a1", "pain")))
    video = _note(
        _section("imaging_review", _claim("v1", "AP knee film on screen", "visual")),
        provider="gemini",
    )
    merged = fusion.merge_parallel_notes(audio, video)
    img = merged.get_section("imaging_review")
    assert img is not None and img.claims[0].text.startswith("AP knee film")


def test_no_video_note_returns_audio_copy() -> None:
    audio = _note(_section("hpi", _claim("a1", "pain")))
    merged = fusion.merge_parallel_notes(audio, None)
    assert merged.get_section("hpi") is not None
    # A copy, not the same object (merge must not mutate the input).
    assert merged is not audio


def test_merge_does_not_mutate_inputs() -> None:
    audio = _note(_section("physical_exam", _claim("a1", "audio exam")))
    video = _note(
        _section("physical_exam", _claim("v1", "video exam", "visual")), provider="gemini"
    )
    fusion.merge_parallel_notes(audio, video)
    # Inputs untouched.
    assert [c.id for c in audio.get_section("physical_exam").claims] == ["a1"]
    assert [c.id for c in video.get_section("physical_exam").claims] == ["v1"]


def test_merged_provider_names_both_sources() -> None:
    audio = _note(_section("hpi", _claim("a1", "x")), provider="anthropic")
    video = _note(
        _section("physical_exam", _claim("v1", "y", "visual")), provider="gemini"
    )
    merged = fusion.merge_parallel_notes(audio, video)
    assert "anthropic" in merged.provider_used and "gemini" in merged.provider_used
    assert merged.stage == 2


def test_note_has_conflicts_detects_surfaced_conflict() -> None:
    audio = _note(_section("physical_exam", _claim("a1", "audio finding")))
    video = _note(
        _section("physical_exam", _claim("v1", "video finding", "visual")), provider="gemini"
    )
    merged = fusion.merge_parallel_notes(audio, video)
    assert fusion.note_has_conflicts(merged) is True


def test_note_has_no_conflicts_when_sections_disjoint() -> None:
    audio = _note(_section("hpi", _claim("a1", "history")))
    video = _note(
        _section("physical_exam", _claim("v1", "finding", "visual")), provider="gemini"
    )
    merged = fusion.merge_parallel_notes(audio, video)
    assert fusion.note_has_conflicts(merged) is False


# ── generate_video_note (mocked) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_video_note_retags_claims_as_visual() -> None:
    from app.core.types import Template, TemplateSection

    template = Template(
        key="orthopedic_surgery", display_name="Orthopedic Surgery",
        sections=[TemplateSection(id="physical_exam", title="Physical Exam", required=True)],
    )
    # The note engine returns claims tagged transcript (it can't know its input
    # was a pseudo-transcript); generate_video_note must re-tag them visual.
    engine_note = _note(
        _section("physical_exam", _claim("c1", "reduced flexion", "transcript")),
        provider="gemini",
    )
    provider = MagicMock()
    provider.generate_note = AsyncMock(return_value=engine_note)
    registry = MagicMock()
    registry.get_note_provider_with_fallback = MagicMock(return_value=provider)

    with (
        patch.object(fusion, "get_registry", return_value=registry),
        patch.object(
            fusion, "caption_visual_evidence",
            AsyncMock(return_value=[_caption(1000, "reduced knee flexion")]),
        ),
    ):
        note = await fusion.generate_video_note(
            "s1", evidence=[MagicMock()], template=template, grounded=True
        )
    assert note is not None
    claim = note.get_section("physical_exam").claims[0]
    assert claim.source_type == "visual"


@pytest.mark.asyncio
async def test_generate_video_note_none_when_no_captions() -> None:
    from app.core.types import Template, TemplateSection

    template = Template(
        key="orthopedic_surgery", display_name="Orthopedic Surgery",
        sections=[TemplateSection(id="physical_exam", title="Physical Exam", required=True)],
    )
    with (
        patch.object(fusion, "get_registry", return_value=MagicMock()),
        patch.object(
            fusion, "caption_visual_evidence",
            AsyncMock(return_value=[_caption(1000, "nothing", conf="low")]),
        ),
    ):
        # Low-confidence caption is filtered → no segments → no video note.
        note = await fusion.generate_video_note(
            "s1", evidence=[MagicMock()], template=template, grounded=False
        )
    assert note is None
