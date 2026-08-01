"""Correction memory — capture layer.

Locks the pure diff (which claims in which edited sections became corrections)
and the record_corrections persistence contract. The diff is what everything
downstream (classification, rule distillation) mines, so its boundaries are
pinned precisely: only physician-edited claims, only in edited sections, only
when the text actually changed.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.corrections.service import (
    _corrections_from_note,
    record_corrections,
)


def _claim(
    cid: str, text: str, *, edited: bool = False, original: str | None = None
) -> NoteClaim:
    return NoteClaim(
        id=cid, text=text, source_type="transcript", source_id="seg_1",
        physician_edited=edited, original_text=original,
    )


def _note(*sections: NoteSection) -> Note:
    return Note(
        session_id="s1", stage=2, version=3, provider_used="anthropic",
        specialty="orthopedic_surgery", sections=list(sections),
    )


# ── pure diff ────────────────────────────────────────────────────────────────


def test_edited_claim_in_edited_section_is_a_correction() -> None:
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("c1", "3-week knee pain", edited=True, original="knee pain"),
        ]),
    )
    diffs = _corrections_from_note(note, ["hpi"])
    assert diffs == [("hpi", "c1", "knee pain", "3-week knee pain")]


def test_unedited_claim_is_not_a_correction() -> None:
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("c1", "knee pain"),  # physician_edited=False
        ]),
    )
    assert _corrections_from_note(note, ["hpi"]) == []


def test_claim_in_unedited_section_is_ignored() -> None:
    note = _note(
        NoteSection(id="plan", title="Plan", status="populated", claims=[
            _claim("c1", "new plan", edited=True, original="old plan"),
        ]),
    )
    # "plan" was not in the edited set → not captured.
    assert _corrections_from_note(note, ["hpi"]) == []


def test_no_op_edit_same_text_is_not_a_correction() -> None:
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("c1", "same", edited=True, original="same"),
        ]),
    )
    assert _corrections_from_note(note, ["hpi"]) == []


def test_edited_claim_without_original_is_skipped() -> None:
    # original_text None (shouldn't happen post-edit, but be defensive) → skip.
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("c1", "text", edited=True, original=None),
        ]),
    )
    assert _corrections_from_note(note, ["hpi"]) == []


def test_multiple_corrections_ordered_by_section_then_claim() -> None:
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("a", "A2", edited=True, original="A1"),
        ]),
        NoteSection(id="physical_exam", title="Exam", status="populated", claims=[
            _claim("b", "B2", edited=True, original="B1"),
            _claim("c", "C1"),  # unedited — skipped
        ]),
    )
    diffs = _corrections_from_note(note, ["hpi", "physical_exam"])
    assert [d[1] for d in diffs] == ["a", "b"]


# ── persistence ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_corrections_adds_one_row_per_diff() -> None:
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("c1", "new", edited=True, original="old"),
        ]),
    )
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    n = await record_corrections(uuid.uuid4(), uuid.uuid4(), note, ["hpi"], db)
    assert n == 1
    assert db.add.call_count == 1
    row = db.add.call_args.args[0]
    assert row.before_text == "old" and row.after_text == "new"
    assert row.section_id == "hpi" and row.note_version == 3
    assert row.classification is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_corrections_empty_diff_no_flush() -> None:
    note = _note(
        NoteSection(id="hpi", title="HPI", status="populated", claims=[
            _claim("c1", "unchanged"),
        ]),
    )
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    n = await record_corrections(uuid.uuid4(), uuid.uuid4(), note, ["hpi"], db)
    assert n == 0
    db.add.assert_not_called()
    db.flush.assert_not_awaited()  # nothing to flush
