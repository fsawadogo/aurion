"""M-01: speaker tag PATCH schema + allowed-speaker validation.

iOS performs on-device speaker separation against the enrolled physician
embedding (the embedding itself never leaves the device). This test
covers the wire-format model: the tags themselves are NOT biometric data,
just labels and confidences, but the speaker label is strictly limited to
{"physician", "other"} — Aurion explicitly does NOT perform multi-
speaker diarization (CLAUDE.md §"What NOT to Build").
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.transcription import Speaker, SpeakerTag, SpeakerTagBatch


class TestSpeakerTag:
    def test_valid_physician(self):
        tag = SpeakerTag(segment_id="seg_001", speaker="physician", confidence=0.92)
        assert tag.speaker == "physician"

    def test_valid_other(self):
        tag = SpeakerTag(segment_id="seg_001", speaker="other", confidence=0.18)
        assert tag.speaker == "other"

    def test_rejects_blank_segment_id(self):
        with pytest.raises(ValidationError):
            SpeakerTag(segment_id="", speaker="physician", confidence=0.9)

    def test_rejects_confidence_above_one(self):
        with pytest.raises(ValidationError):
            SpeakerTag(segment_id="seg_001", speaker="physician", confidence=1.5)

    def test_rejects_negative_confidence(self):
        with pytest.raises(ValidationError):
            SpeakerTag(segment_id="seg_001", speaker="other", confidence=-0.1)


class TestSpeakerTagBatch:
    def test_empty_batch_allowed(self):
        # An enrolled-but-silent session produces no tags. The endpoint
        # must accept the empty batch — Stage 1 still proceeds.
        batch = SpeakerTagBatch(tags=[])
        assert batch.tags == []

    def test_mixed_batch(self):
        batch = SpeakerTagBatch(tags=[
            SpeakerTag(segment_id="seg_001", speaker="physician", confidence=0.95),
            SpeakerTag(segment_id="seg_002", speaker="other", confidence=0.42),
        ])
        assert len(batch.tags) == 2
        assert {t.speaker for t in batch.tags} == {"physician", "other"}


class TestAllowedSpeakers:
    def test_rejects_unknown_speaker(self):
        # CLAUDE.md: no multi-speaker diarization. Pydantic enforces it.
        with pytest.raises(ValidationError):
            SpeakerTag(segment_id="seg_001", speaker="nurse", confidence=0.9)

    def test_speaker_type_alias(self):
        # The Speaker alias is the single source of truth for allowed values.
        # Pydantic generates the schema from it; the route signature uses it.
        import typing
        args = typing.get_args(Speaker)
        assert set(args) == {"physician", "other"}
