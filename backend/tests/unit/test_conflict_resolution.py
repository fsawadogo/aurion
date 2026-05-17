"""M-10: explicit conflict resolution workflow.

Validates the `resolve_conflict` service function. Each resolution action
produces a new immutable note version; the original conflict is preserved
in version history (verified by checking that the input note isn't mutated).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.note_gen.service import resolve_conflict


def _note_with_conflict() -> Note:
    return Note(
        session_id=str(uuid.uuid4()),
        stage=2,
        version=2,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="imaging_review",
                title="Imaging Review",
                status="populated",
                claims=[
                    NoteClaim(
                        id="vc1",
                        text="X-ray shows healing fracture, callus visible.",
                        source_type="visual",
                        source_id="frame_14500",
                    ),
                    NoteClaim(
                        id="conflict_1",
                        text="Visual shows post-op hardware; audio mentioned conservative care.",
                        source_type="visual",
                        source_id="frame_14600",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def patched_persistence():
    """Patch get_latest_note / create_note_version so tests are pure logic."""
    with (
        patch(
            "app.modules.note_gen.service.get_latest_note",
            new_callable=AsyncMock,
        ) as mock_get,
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        yield mock_get, mock_create


@pytest.mark.asyncio
async def test_accept_visual_marks_physician_edited(patched_persistence):
    mock_get, mock_create = patched_persistence
    original = _note_with_conflict()
    mock_get.return_value = original

    result = await resolve_conflict(
        session_id=original.session_id,
        claim_id="conflict_1",
        action="accept_visual",
        resolution_text=None,
        db=AsyncMock(),
    )

    conflict = result.sections[0].claims[1]
    assert conflict.physician_edited is True
    assert conflict.text.startswith("Visual shows post-op hardware")  # text unchanged
    assert conflict.original_text == conflict.text
    # Original note untouched (versioning invariant)
    assert original.sections[0].claims[1].physician_edited is False
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_reject_visual_removes_conflict_claim(patched_persistence):
    mock_get, _ = patched_persistence
    original = _note_with_conflict()
    mock_get.return_value = original

    result = await resolve_conflict(
        session_id=original.session_id,
        claim_id="conflict_1",
        action="reject_visual",
        resolution_text=None,
        db=AsyncMock(),
    )

    claim_ids = [c.id for c in result.sections[0].claims]
    assert "conflict_1" not in claim_ids
    assert "vc1" in claim_ids  # non-conflict claim survives
    # Original is preserved in history
    assert len(original.sections[0].claims) == 2


@pytest.mark.asyncio
async def test_edit_replaces_text_and_preserves_original(patched_persistence):
    mock_get, _ = patched_persistence
    original = _note_with_conflict()
    mock_get.return_value = original
    original_text = original.sections[0].claims[1].text

    result = await resolve_conflict(
        session_id=original.session_id,
        claim_id="conflict_1",
        action="edit",
        resolution_text="Physician confirms post-op hardware; care plan updated.",
        db=AsyncMock(),
    )

    conflict = result.sections[0].claims[1]
    assert conflict.text == "Physician confirms post-op hardware; care plan updated."
    assert conflict.physician_edited is True
    assert conflict.original_text == original_text


@pytest.mark.asyncio
async def test_unknown_action_raises(patched_persistence):
    mock_get, _ = patched_persistence
    mock_get.return_value = _note_with_conflict()

    with pytest.raises(ValueError, match="Unknown resolution action"):
        await resolve_conflict(
            session_id=str(uuid.uuid4()),
            claim_id="conflict_1",
            action="defer",
            resolution_text=None,
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_edit_without_text_raises(patched_persistence):
    mock_get, _ = patched_persistence
    mock_get.return_value = _note_with_conflict()

    with pytest.raises(ValueError, match="resolution_text"):
        await resolve_conflict(
            session_id=str(uuid.uuid4()),
            claim_id="conflict_1",
            action="edit",
            resolution_text="",
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_missing_claim_raises(patched_persistence):
    mock_get, _ = patched_persistence
    mock_get.return_value = _note_with_conflict()

    with pytest.raises(ValueError, match="not found"):
        await resolve_conflict(
            session_id=str(uuid.uuid4()),
            claim_id="conflict_nonexistent",
            action="accept_visual",
            resolution_text=None,
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_missing_note_raises(patched_persistence):
    mock_get, _ = patched_persistence
    mock_get.return_value = None

    with pytest.raises(ValueError, match="No note found"):
        await resolve_conflict(
            session_id=str(uuid.uuid4()),
            claim_id="conflict_1",
            action="accept_visual",
            resolution_text=None,
            db=AsyncMock(),
        )
