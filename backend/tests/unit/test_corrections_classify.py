"""Correction memory — classification pass (typo / semantic / medical).

Locks the label normalisation (coercing a chatty model reply to one of the
three labels, defaulting to "unrecognised → skip"), the single-edit classifier
with the provider mocked, and the batch's per-label accounting + the safety
rule that a medical change is never mislabelled as style when the model says so.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.corrections.classify as classify

# ── normalisation ────────────────────────────────────────────────────────────


def test_normalise_exact_label() -> None:
    assert classify._normalise("typo") == "typo"
    assert classify._normalise("semantic") == "semantic"
    assert classify._normalise("medical") == "medical"


def test_normalise_strips_punctuation_and_case() -> None:
    assert classify._normalise("Medical.") == "medical"
    assert classify._normalise("  TYPO  ") == "typo"
    assert classify._normalise("semantic — the wording changed") == "semantic"


def test_normalise_unrecognised_is_none() -> None:
    assert classify._normalise("I think this is a spelling fix") is None
    assert classify._normalise("") is None
    assert classify._normalise("stylistic") is None


# ── single classify ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_one_returns_label() -> None:
    provider = MagicMock()
    provider.generate_text = AsyncMock(return_value="medical")
    registry = MagicMock()
    registry.get_note_provider_with_fallback = MagicMock(return_value=provider)
    with patch.object(classify, "get_registry", return_value=registry):
        label = await classify.classify_one(
            "no acute distress", "in moderate distress"
        )
    assert label == "medical"


@pytest.mark.asyncio
async def test_classify_one_bad_reply_is_none() -> None:
    provider = MagicMock()
    provider.generate_text = AsyncMock(return_value="hmm not sure")
    registry = MagicMock()
    registry.get_note_provider_with_fallback = MagicMock(return_value=provider)
    with patch.object(classify, "get_registry", return_value=registry):
        label = await classify.classify_one("a", "b")
    assert label is None


# ── batch ────────────────────────────────────────────────────────────────────


def _row(before: str, after: str):
    return SimpleNamespace(
        id=uuid.uuid4(), before_text=before, after_text=after, classification=None
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


@pytest.mark.asyncio
async def test_batch_fills_labels_and_counts() -> None:
    rows = [_row("teh", "the"), _row("client", "patient"), _row("90", "130")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(rows))
    db.commit = AsyncMock()

    async def fake_classify_one(before, after):
        return {"teh": "typo", "client": "semantic", "90": "medical"}[before]

    with patch.object(classify, "classify_one", side_effect=fake_classify_one):
        counts = await classify.classify_pending_for_clinician(uuid.uuid4(), db)

    assert counts == {"typo": 1, "semantic": 1, "medical": 1, "skipped": 0}
    assert [r.classification for r in rows] == ["typo", "semantic", "medical"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_skips_unclassifiable_and_survives_errors() -> None:
    rows = [_row("a", "b"), _row("c", "d")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(rows))
    db.commit = AsyncMock()

    async def flaky(before, after):
        if before == "a":
            raise RuntimeError("provider down")
        return None  # unrecognised label

    with patch.object(classify, "classify_one", side_effect=flaky):
        counts = await classify.classify_pending_for_clinician(uuid.uuid4(), db)

    # One errored, one unrecognised → both skipped; nothing labelled → no commit.
    assert counts["skipped"] == 2
    assert all(r.classification is None for r in rows)
    db.commit.assert_not_awaited()
