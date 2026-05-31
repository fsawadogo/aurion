"""Unit tests for the semantic trigger classifier (Tier 2 / item F)."""

from __future__ import annotations

import pytest

from app.core.types import Transcript, TranscriptSegment
from app.modules.transcription import semantic_trigger as st
from app.modules.transcription.trigger_classifier import classify_triggers


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch) -> None:
    st._clear_cache_for_tests()
    # Default: off. Each test enables explicitly when it wants the semantic path.
    monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "0")
    monkeypatch.setattr(st, "_OPENAI_API_KEY", "sk-test")


# ── Pure helpers ──────────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors_return_one(self) -> None:
        assert st._cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_zero(self) -> None:
        assert st._cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors_return_minus_one(self) -> None:
        assert st._cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_length_mismatch_returns_zero(self) -> None:
        assert st._cosine_similarity([1, 2], [1, 2, 3]) == 0.0

    def test_zero_vector_returns_zero(self) -> None:
        assert st._cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


# ── classify_unmatched_segments behaviour ─────────────────────────────


class TestClassifyUnmatched:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "0")
        result = await st.classify_unmatched_segments(
            [("seg_001", "any text")]
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "1")
        monkeypatch.setattr(st, "_OPENAI_API_KEY", "")
        result = await st.classify_unmatched_segments(
            [("seg_001", "any text")]
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_without_call(self) -> None:
        # No HTTP call should happen for empty input even when enabled.
        result = await st.classify_unmatched_segments([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_match_above_threshold_returns_decision(self, monkeypatch) -> None:
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "1")

        # Hand-built vectors: segment vector aligns with the
        # active_physical_examination category embedding.
        category_vec = [1.0, 0.0, 0.0]
        segment_vec = [0.95, 0.05, 0.0]
        other_vec = [0.0, 1.0, 0.0]

        # First call: embed the 3 category descriptions.
        # Second call: embed the segments.
        async def fake_embed(texts: list[str]) -> list[list[float]]:
            if len(texts) == len(st.TRIGGER_DESCRIPTIONS):
                # Category descriptions in dict order
                return [
                    other_vec,        # live_imaging_review (mismatch)
                    category_vec,     # active_physical_examination ← match
                    other_vec,        # wound_tissue_assessment (mismatch)
                ]
            return [segment_vec]

        monkeypatch.setattr(st, "_embed_batch", fake_embed)
        out = await st.classify_unmatched_segments(
            [("seg_001", "let me check your knee")]
        )
        assert out == {"seg_001": "active_physical_examination"}

    @pytest.mark.asyncio
    async def test_below_threshold_returns_no_decision(self, monkeypatch) -> None:
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "1")
        # Weak match: segment vector cos-sim well below the 0.45 default.
        async def fake_embed(texts: list[str]) -> list[list[float]]:
            if len(texts) == len(st.TRIGGER_DESCRIPTIONS):
                return [[1.0, 0.0, 0.0]] * len(st.TRIGGER_DESCRIPTIONS)
            return [[0.1, 0.99, 0.0]]  # ~0.1 cosine vs every category

        monkeypatch.setattr(st, "_embed_batch", fake_embed)
        out = await st.classify_unmatched_segments(
            [("seg_001", "how is the weather")]
        )
        assert out == {}

    @pytest.mark.asyncio
    async def test_embed_failure_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "1")
        async def boom(_texts: list[str]) -> list[list[float]]:
            raise RuntimeError("openai down")
        monkeypatch.setattr(st, "_embed_batch", boom)
        out = await st.classify_unmatched_segments(
            [("seg_001", "any text")]
        )
        assert out == {}


# ── Integration: classify_triggers wires the semantic fallback ────────


class TestClassifyTriggersIntegration:
    def _transcript(self, *texts: str) -> Transcript:
        return Transcript(
            session_id="s",
            provider_used="whisper",
            segments=[
                TranscriptSegment(
                    id=f"seg_{i:03d}", start_ms=i * 1000,
                    end_ms=(i + 1) * 1000, text=t,
                )
                for i, t in enumerate(texts)
            ],
        )

    @pytest.mark.asyncio
    async def test_keyword_pass_runs_when_semantic_disabled(self) -> None:
        # "range of motion" is a default keyword for active_physical_examination
        out = await classify_triggers(
            self._transcript(
                "we'll test the range of motion now",
                "just chatting about the weather",
            )
        )
        assert out.segments[0].is_visual_trigger is True
        assert out.segments[0].trigger_type == "active_physical_examination"
        # Second segment misses keywords — without semantic, stays unflagged.
        assert out.segments[1].is_visual_trigger is False

    @pytest.mark.asyncio
    async def test_semantic_pass_flags_paraphrase(self, monkeypatch) -> None:
        """The phrase 'can you bend your knee' isn't in the keyword
        list, but it semantically maps to active_physical_examination."""
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "1")
        st._clear_cache_for_tests()

        async def fake_classify(_unmatched):
            # Force the semantic layer to flag the first segment.
            return {"seg_000": "active_physical_examination"}

        monkeypatch.setattr(
            "app.modules.transcription.trigger_classifier."
            "classify_unmatched_segments",
            fake_classify,
        )

        out = await classify_triggers(
            self._transcript("can you bend your knee for me")
        )
        assert out.segments[0].is_visual_trigger is True
        assert out.segments[0].trigger_type == "active_physical_examination"

    @pytest.mark.asyncio
    async def test_suppression_overrides_semantic(self, monkeypatch) -> None:
        """A suppressed segment is never added to ``unmatched``, so the
        semantic call is skipped entirely (no wasted API spend) and
        the segment stays unflagged — retrospective narration is not
        a live event."""
        monkeypatch.setenv("AURION_SEMANTIC_TRIGGER_ENABLED", "1")
        st._clear_cache_for_tests()
        called = False

        async def fake_classify(_unmatched):
            nonlocal called
            called = True
            return {}

        monkeypatch.setattr(
            "app.modules.transcription.trigger_classifier."
            "classify_unmatched_segments",
            fake_classify,
        )

        out = await classify_triggers(
            self._transcript("at the last visit we examined the knee")
        )
        assert out.segments[0].is_visual_trigger is False
        # No call when the only candidate was suppressed.
        assert called is False
