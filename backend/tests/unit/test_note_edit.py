"""Unit tests for note editing (edit_note service function).

Verifies:
- New version created with incremented version number
- Original version is preserved (immutable)
- Edits apply to correct sections
- Missing sections are skipped gracefully
- Empty note raises ValueError
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import Note, NoteClaim, NoteSection


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_note(session_id: str, version: int = 1, stage: int = 1) -> Note:
    """Build a sample note with two populated sections."""
    return Note(
        session_id=session_id,
        stage=stage,
        version=version,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.78,
        sections=[
            NoteSection(
                id="physical_exam",
                title="Physical Examination",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_001",
                        text="Physician noted tenderness on palpation at the medial joint line.",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="There is tenderness on palpation at the medial joint line.",
                    )
                ],
            ),
            NoteSection(
                id="assessment",
                title="Assessment",
                status="populated",
                claims=[
                    NoteClaim(
                        id="claim_002",
                        text="Physician noted restricted range of motion.",
                        source_type="transcript",
                        source_id="seg_002",
                        source_quote="Range of motion is restricted.",
                    )
                ],
            ),
            NoteSection(
                id="imaging_review",
                title="Imaging Review",
                status="not_captured",
                claims=[],
            ),
        ],
    )


def _make_version_record(note: Note) -> MagicMock:
    """Create a mock NoteVersionModel from a Note."""
    record = MagicMock()
    record.session_id = uuid.UUID(note.session_id)
    record.version = note.version
    record.stage = note.stage
    record.provider_used = note.provider_used
    record.specialty = note.specialty
    record.completeness_score = note.completeness_score
    record.content = json.dumps(note.model_dump(), default=str)
    record.is_approved = False
    return record


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_note_creates_new_version():
    """edit_note should create a new version with incremented version number."""
    session_id = str(uuid.uuid4())
    original_note = _make_note(session_id, version=2)

    db = AsyncMock()

    with (
        patch(
            "app.modules.note_gen.service.get_latest_note",
            new_callable=AsyncMock,
            return_value=original_note,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ) as mock_create_version,
    ):
        from app.modules.note_gen.service import edit_note

        result = await edit_note(
            session_id,
            {"physical_exam": "Updated physical exam text."},
            db,
        )

    # create_note_version was called with the edited note
    mock_create_version.assert_called_once()
    call_args = mock_create_version.call_args
    assert call_args[0][0] == session_id  # session_id
    edited_note_arg = call_args[0][1]  # the Note object
    assert isinstance(edited_note_arg, Note)

    # The result should have the updated text
    pe_section = result.get_section("physical_exam")
    assert pe_section is not None
    assert pe_section.claims[0].text == "Updated physical exam text."


@pytest.mark.asyncio
async def test_edit_note_preserves_original():
    """The original note object should not be mutated by edit_note."""
    session_id = str(uuid.uuid4())
    original_note = _make_note(session_id, version=1)
    original_text = original_note.sections[0].claims[0].text

    db = AsyncMock()

    with (
        patch(
            "app.modules.note_gen.service.get_latest_note",
            new_callable=AsyncMock,
            return_value=original_note,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
    ):
        from app.modules.note_gen.service import edit_note

        await edit_note(
            session_id,
            {"physical_exam": "Completely different text."},
            db,
        )

    # Original note should be unchanged because edit_note does model_copy(deep=True)
    assert original_note.sections[0].claims[0].text == original_text


@pytest.mark.asyncio
async def test_edit_note_applies_to_correct_sections():
    """Edits should only modify the targeted sections, leaving others intact."""
    session_id = str(uuid.uuid4())
    original_note = _make_note(session_id, version=3)

    db = AsyncMock()

    with (
        patch(
            "app.modules.note_gen.service.get_latest_note",
            new_callable=AsyncMock,
            return_value=original_note,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
    ):
        from app.modules.note_gen.service import edit_note

        result = await edit_note(
            session_id,
            {"assessment": "New assessment text."},
            db,
        )

    # assessment should be updated
    assessment = result.get_section("assessment")
    assert assessment is not None
    assert assessment.claims[0].text == "New assessment text."

    # physical_exam should be unchanged
    pe = result.get_section("physical_exam")
    assert pe is not None
    assert pe.claims[0].text == "Physician noted tenderness on palpation at the medial joint line."


@pytest.mark.asyncio
async def test_edit_note_skips_missing_section():
    """Editing a section that does not exist in the note should be silently skipped."""
    session_id = str(uuid.uuid4())
    original_note = _make_note(session_id, version=1)

    db = AsyncMock()

    with (
        patch(
            "app.modules.note_gen.service.get_latest_note",
            new_callable=AsyncMock,
            return_value=original_note,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
    ):
        from app.modules.note_gen.service import edit_note

        # "nonexistent_section" does not exist -- should not raise
        result = await edit_note(
            session_id,
            {"nonexistent_section": "Should be ignored."},
            db,
        )

    # All original sections should be intact
    assert len(result.sections) == 3
    assert result.get_section("nonexistent_section") is None


@pytest.mark.asyncio
async def test_edit_note_creates_claim_for_empty_section():
    """Editing an empty section should create a new claim and set status to populated."""
    session_id = str(uuid.uuid4())
    original_note = _make_note(session_id, version=1)

    db = AsyncMock()

    with (
        patch(
            "app.modules.note_gen.service.get_latest_note",
            new_callable=AsyncMock,
            return_value=original_note,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
    ):
        from app.modules.note_gen.service import edit_note

        result = await edit_note(
            session_id,
            {"imaging_review": "No fracture visible on X-ray."},
            db,
        )

    imaging = result.get_section("imaging_review")
    assert imaging is not None
    assert len(imaging.claims) == 1
    assert imaging.claims[0].text == "No fracture visible on X-ray."
    assert imaging.claims[0].source_id == "physician_edit"
    assert imaging.status == "populated"


@pytest.mark.asyncio
async def test_edit_note_raises_when_no_note_exists():
    """edit_note should raise ValueError when no note exists for the session."""
    session_id = str(uuid.uuid4())

    db = AsyncMock()

    with patch(
        "app.modules.note_gen.service.get_latest_note",
        new_callable=AsyncMock,
        return_value=None,
    ):
        from app.modules.note_gen.service import edit_note

        with pytest.raises(ValueError, match="No note found"):
            await edit_note(session_id, {"physical_exam": "text"}, db)
