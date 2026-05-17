"""M-09 + B-04: note detail helpers — citation expansion, conflict summary,
frame-id parsing. The full endpoint is covered in integration; here we
unit-test the pure helpers so regressions surface fast.
"""

from __future__ import annotations

from app.api.v1.notes import (
    _build_citations,
    _is_unresolved_conflict,
    _parse_frame_timestamp,
    _summarize_conflicts,
)
from app.core.types import (
    Note,
    NoteClaim,
    NoteSection,
    Transcript,
    TranscriptSegment,
)


def _make_note() -> Note:
    return Note(
        session_id="sess-1",
        stage=2,
        version=3,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="physical_exam",
                claims=[
                    NoteClaim(
                        id="c1",
                        text="Tenderness noted.",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="There is tenderness.",
                    ),
                ],
            ),
            NoteSection(
                id="imaging_review",
                claims=[
                    NoteClaim(
                        id="vc1",
                        text="X-ray frame shows knee joint.",
                        source_type="visual",
                        source_id="frame_14500",
                    ),
                    NoteClaim(
                        id="conflict_1",
                        text="Visual conflicts with audio narration.",
                        source_type="visual",
                        source_id="frame_14600",
                    ),
                ],
            ),
            NoteSection(
                id="investigations",
                claims=[
                    NoteClaim(
                        id="sclaim_screen_18300_1",
                        text="Screen-captured Hemoglobin: 138 g/L",
                        source_type="screen",
                        source_id="screen_18300",
                    ),
                ],
            ),
        ],
    )


class TestParseFrameTimestamp:
    def test_video_frame(self):
        assert _parse_frame_timestamp("frame_14500") == 14500

    def test_screen_frame(self):
        assert _parse_frame_timestamp("screen_18300") == 18300

    def test_non_numeric_suffix(self):
        assert _parse_frame_timestamp("seg_abc") is None

    def test_no_underscore(self):
        assert _parse_frame_timestamp("seg001") is None


class TestSummarizeConflicts:
    def test_unresolved_conflict_surfaces(self):
        state = _summarize_conflicts(_make_note())
        assert state.has_unresolved is True
        assert state.unresolved_count == 1
        assert state.unresolved_section_ids == ["imaging_review"]
        assert state.unresolved_claim_ids == ["conflict_1"]

    def test_edited_conflict_is_resolved(self):
        # Once the physician edits a conflict claim it no longer blocks approval.
        note = _make_note()
        conflict = note.sections[1].claims[1]
        conflict.physician_edited = True
        conflict.original_text = conflict.text
        conflict.text = "Resolved by physician."

        state = _summarize_conflicts(note)
        assert state.has_unresolved is False
        assert state.unresolved_count == 0

    def test_no_conflicts(self):
        note = _make_note()
        # Drop the conflict claim entirely.
        note.sections[1].claims.pop()
        state = _summarize_conflicts(note)
        assert state.has_unresolved is False
        assert state.unresolved_claim_ids == []


class TestIsUnresolvedConflict:
    def test_only_visual_conflict_prefix_counts(self):
        # A transcript claim, even with `conflict_` id, is not a vision conflict.
        claim = NoteClaim(
            id="conflict_99",
            text="...",
            source_type="transcript",
            source_id="seg_010",
        )
        assert _is_unresolved_conflict(claim) is False


class TestBuildCitations:
    def test_transcript_claim_expands_from_transcript(self):
        note = _make_note()
        transcript = Transcript(
            session_id="sess-1",
            provider_used="whisper",
            segments=[
                TranscriptSegment(
                    id="seg_001",
                    start_ms=1000,
                    end_ms=2500,
                    text="Patient reports knee pain.",
                    speaker="physician",
                ),
            ],
        )
        citations = _build_citations(note, transcript, session_id="sess-1")

        assert "c1" in citations
        assert citations["c1"].transcript_text == "Patient reports knee pain."
        assert citations["c1"].transcript_speaker == "physician"
        assert citations["c1"].transcript_start_ms == 1000

    def test_visual_claim_builds_s3_key(self):
        citations = _build_citations(_make_note(), transcript=None, session_id="sess-1")
        assert citations["vc1"].source_type == "visual"
        assert citations["vc1"].frame_timestamp_ms == 14500
        assert citations["vc1"].frame_s3_key == "frames/sess-1/14500.jpg"

    def test_screen_claim_uses_screen_frames_prefix(self):
        citations = _build_citations(_make_note(), transcript=None, session_id="sess-1")
        screen = citations["sclaim_screen_18300_1"]
        assert screen.source_type == "screen"
        assert screen.frame_timestamp_ms == 18300
        assert screen.frame_s3_key == "screen_frames/sess-1/18300.jpg"

    def test_missing_transcript_falls_back_to_quote(self):
        # No transcript persisted yet — quote captured at claim time is the fallback.
        citations = _build_citations(_make_note(), transcript=None, session_id="sess-1")
        assert citations["c1"].transcript_text == "There is tenderness."
