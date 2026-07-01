"""Server-side conflict gate on note approval (#606).

`approve_note` must refuse to sign off a note that still has unresolved
Stage 2 visual CONFLICTS — a defense-in-depth invariant that holds no
matter which caller invokes approval (the HTTP `/approve` route pre-checks
too, but the video-import auto-approve path calls the service directly).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.note_gen import service as note_service


def _conflict_claim(resolved: bool = False) -> NoteClaim:
    return NoteClaim(
        id="conflict_001",
        text="Visual finding disagrees with the dictated exam.",
        source_type="visual",
        source_id="frame_00001",
        physician_edited=resolved,
    )


def _note(claims: list[NoteClaim]) -> Note:
    return Note(
        session_id="sess",
        stage=2,
        version=2,
        provider_used="anthropic",
        specialty="general",
        sections=[NoteSection(id="physical_exam", claims=claims)],
    )


# ── predicate ─────────────────────────────────────────────────────────────


def test_open_visual_conflict_is_unresolved() -> None:
    assert note_service.is_unresolved_conflict_claim(_conflict_claim()) is True


def test_physician_edited_conflict_is_resolved() -> None:
    assert (
        note_service.is_unresolved_conflict_claim(_conflict_claim(resolved=True))
        is False
    )


def test_non_conflict_visual_claim_is_not_a_conflict() -> None:
    claim = NoteClaim(
        id="frame_00001", text="x", source_type="visual", source_id="frame_00001"
    )
    assert note_service.is_unresolved_conflict_claim(claim) is False


def test_conflict_prefixed_transcript_claim_is_not_a_visual_conflict() -> None:
    # id starts with conflict_ but it's an audio claim — not a vision conflict.
    claim = NoteClaim(
        id="conflict_001", text="x", source_type="transcript", source_id="seg_1"
    )
    assert note_service.is_unresolved_conflict_claim(claim) is False


def test_unresolved_conflict_claim_ids_collects_sections_and_claims() -> None:
    note = _note(
        [
            _conflict_claim(),
            NoteClaim(id="seg", text="x", source_type="transcript", source_id="seg_1"),
        ]
    )
    sections, claims = note_service.unresolved_conflict_claim_ids(note)
    assert sections == ["physical_exam"]
    assert claims == ["conflict_001"]


# ── approve_note guard ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_note_raises_on_unresolved_conflict(monkeypatch) -> None:
    version_record = MagicMock(is_approved=False, version=2)
    monkeypatch.setattr(
        note_service.note_repo,
        "get_latest_version",
        AsyncMock(return_value=version_record),
    )
    monkeypatch.setattr(
        note_service, "_deserialize_note", lambda _vr: _note([_conflict_claim()])
    )
    db = AsyncMock()

    with pytest.raises(note_service.UnresolvedConflictError) as excinfo:
        await note_service.approve_note("sess", db)

    assert excinfo.value.claim_ids == ["conflict_001"]
    assert excinfo.value.section_ids == ["physical_exam"]
    # The note must NOT be flipped to approved and nothing flushed.
    assert version_record.is_approved is False
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_note_succeeds_when_conflicts_resolved(monkeypatch) -> None:
    version_record = MagicMock(is_approved=False, version=2)
    monkeypatch.setattr(
        note_service.note_repo,
        "get_latest_version",
        AsyncMock(return_value=version_record),
    )
    note = _note([_conflict_claim(resolved=True)])
    monkeypatch.setattr(note_service, "_deserialize_note", lambda _vr: note)
    db = AsyncMock()

    result = await note_service.approve_note("sess", db)

    assert result is note
    assert version_record.is_approved is True
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_approve_note_succeeds_with_no_conflicts(monkeypatch) -> None:
    version_record = MagicMock(is_approved=False, version=1)
    monkeypatch.setattr(
        note_service.note_repo,
        "get_latest_version",
        AsyncMock(return_value=version_record),
    )
    note = _note(
        [NoteClaim(id="seg", text="x", source_type="transcript", source_id="seg_1")]
    )
    monkeypatch.setattr(note_service, "_deserialize_note", lambda _vr: note)
    db = AsyncMock()

    result = await note_service.approve_note("sess", db)

    assert result is note
    assert version_record.is_approved is True
