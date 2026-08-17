"""Final approval waits for Stage 2 and requires explicit failure fallback."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import notes
from app.core.types import Note, NoteSection, SessionState


def _note(session_id: uuid.UUID) -> Note:
    return Note(
        session_id=str(session_id),
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.8,
        sections=[NoteSection(id="assessment", status="populated", claims=[])],
    )


async def _approve(stage2_status: str, *, allow_failure: bool = False):
    session_id = uuid.uuid4()
    session = SimpleNamespace(id=session_id, state=SessionState.PROCESSING_STAGE2)
    note = _note(session_id)
    body = notes.FinalApprovalRequest(allow_stage2_failure=allow_failure)
    with (
        patch.object(notes, "get_owned_session_or_404", AsyncMock(return_value=session)),
        patch.object(notes, "get_latest_note", AsyncMock(return_value=note)),
        patch.object(
            notes,
            "get_latest_job",
            AsyncMock(return_value=SimpleNamespace(status=stage2_status)),
        ),
        patch.object(notes, "is_note_approved", AsyncMock(return_value=False)),
        patch.object(notes, "approve_note", AsyncMock(return_value=note)) as approve,
        patch.object(notes, "transition_session", AsyncMock()),
        patch.object(notes, "write_audit", AsyncMock()),
    ):
        result = await notes.approve_final_note(
            session_id, body=body, user=SimpleNamespace(), db=AsyncMock()
        )
    return result, approve


@pytest.mark.asyncio
@pytest.mark.parametrize("job_status", ["pending", "running"])
async def test_final_approval_rejects_in_flight_stage2(job_status: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await _approve(job_status)
    assert exc.value.status_code == 409
    assert "must finish" in exc.value.detail


@pytest.mark.asyncio
async def test_failed_stage2_requires_explicit_audio_only_acknowledgement() -> None:
    with pytest.raises(HTTPException) as exc:
        await _approve("failed")
    assert exc.value.status_code == 409
    assert "audio-only" in exc.value.detail


@pytest.mark.asyncio
async def test_completed_stage2_can_be_finally_approved() -> None:
    result, approve = await _approve("completed")
    assert result.approved is True
    approve.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_stage2_can_be_approved_after_explicit_acknowledgement() -> None:
    result, approve = await _approve("failed", allow_failure=True)
    assert result.approved is True
    approve.assert_awaited_once()
