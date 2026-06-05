"""Stage 1 entry guard against empty / minimal transcripts.

lane-backend/empty-transcript-guard.

CLAUDE.md §"The Single Most Important Constraint" forbids generative
model calls with zero source material. The guard short-circuits Stage 1
BEFORE the provider call when the transcript is missing, has zero
segments, or carries less than ``pipeline.min_transcript_char_threshold``
of usable text.

Each test exercises one of the three branches:

  * missing transcript               → STAGE1_SKIPPED_NO_TRANSCRIPT
  * present but zero segments        → STAGE1_SKIPPED_NO_TRANSCRIPT
  * segments under char threshold    → STAGE1_SKIPPED_LOW_TRANSCRIPT

Every test asserts:

  * ``EmptyTranscriptError`` is raised
  * the registry's ``get_note_provider*`` callsites are NEVER hit (so
    no provider invocation can land), and
  * the appropriate STAGE1_SKIPPED_* audit event is written with the
    correct bounded ``reason`` string.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit_events import AuditEventType
from app.core.types import Transcript, TranscriptSegment
from app.modules.note_gen.service import (
    EmptyTranscriptError,
    generate_stage1_note,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_transcript(segments_text: list[str]) -> Transcript:
    """Build a Transcript with one segment per text entry. Segment ids
    are zero-padded so the audit-side ordering is deterministic."""
    segments = []
    for idx, text in enumerate(segments_text):
        segments.append(
            TranscriptSegment(
                id=f"seg_{idx:03d}",
                start_ms=idx * 1000,
                end_ms=(idx + 1) * 1000,
                text=text,
                is_visual_trigger=False,
                trigger_type=None,
            )
        )
    return Transcript(
        session_id=str(uuid.uuid4()),
        provider_used="whisper",
        segments=segments,
    )


@pytest.fixture
def mock_audit_service():
    """Patch the audit log service so we can assert which event fired
    without touching DynamoDB / LocalStack."""
    audit_mock = MagicMock()
    audit_mock.write_event = AsyncMock()
    with patch(
        "app.modules.note_gen.service.get_audit_log_service",
        return_value=audit_mock,
    ):
        yield audit_mock


@pytest.fixture
def fail_loud_registry():
    """Patch the provider registry so any call raises immediately.

    The guard's whole job is to keep the provider from being called.
    Making the mock fail-loud (rather than returning a mock provider)
    means the test fails the moment the guard regresses — there's no
    'mock returned an empty note' silent-pass.
    """
    fake_registry = MagicMock()
    fake_registry.get_note_provider = MagicMock(
        side_effect=AssertionError(
            "guard violated: get_note_provider called with empty transcript"
        )
    )
    fake_registry.get_note_provider_with_fallback = MagicMock(
        side_effect=AssertionError(
            "guard violated: get_note_provider_with_fallback called with "
            "empty transcript"
        )
    )
    with patch(
        "app.modules.note_gen.service.get_registry",
        return_value=fake_registry,
    ):
        yield fake_registry


# ── Branch 1 — transcript is None ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_fires_when_transcript_is_none(
    mock_audit_service, fail_loud_registry
):
    """``None`` transcript → STAGE1_SKIPPED_NO_TRANSCRIPT, no provider."""
    session_id = str(uuid.uuid4())
    db = AsyncMock()

    with pytest.raises(EmptyTranscriptError) as exc_info:
        await generate_stage1_note(
            transcript=None,  # type: ignore[arg-type] — exercising the guard
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=db,
        )

    assert exc_info.value.reason == "transcript_empty_or_missing"
    assert exc_info.value.transcript_char_count is None

    # Provider never called — fail_loud_registry would have raised
    # AssertionError on access.
    fail_loud_registry.get_note_provider.assert_not_called()
    fail_loud_registry.get_note_provider_with_fallback.assert_not_called()

    # Exactly one audit row, with the right event type and reason.
    mock_audit_service.write_event.assert_awaited_once()
    call = mock_audit_service.write_event.call_args
    assert call.kwargs["session_id"] == session_id
    assert (
        call.kwargs["event_type"]
        == AuditEventType.STAGE1_SKIPPED_NO_TRANSCRIPT
    )
    assert call.kwargs["reason"] == "transcript_empty_or_missing"


# ── Branch 2 — transcript exists but no segments ──────────────────────────


@pytest.mark.asyncio
async def test_guard_fires_when_transcript_has_zero_segments(
    mock_audit_service, fail_loud_registry
):
    """Empty ``segments`` list → STAGE1_SKIPPED_NO_TRANSCRIPT, no provider."""
    session_id = str(uuid.uuid4())
    transcript = _make_transcript([])
    db = AsyncMock()

    with pytest.raises(EmptyTranscriptError) as exc_info:
        await generate_stage1_note(
            transcript=transcript,
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=db,
        )

    assert exc_info.value.reason == "transcript_empty_or_missing"

    fail_loud_registry.get_note_provider.assert_not_called()
    fail_loud_registry.get_note_provider_with_fallback.assert_not_called()

    mock_audit_service.write_event.assert_awaited_once()
    call = mock_audit_service.write_event.call_args
    assert (
        call.kwargs["event_type"]
        == AuditEventType.STAGE1_SKIPPED_NO_TRANSCRIPT
    )


# ── Branch 3 — segments under char threshold ──────────────────────────────


@pytest.mark.asyncio
async def test_guard_fires_when_transcript_below_threshold(
    mock_audit_service, fail_loud_registry
):
    """Segments totaling < threshold chars → STAGE1_SKIPPED_LOW_TRANSCRIPT,
    no provider, ``transcript_char_count`` recorded."""
    session_id = str(uuid.uuid4())
    # 3 segments × "hi" = 6 chars total — well under the default 20.
    transcript = _make_transcript(["hi", "hi", "hi"])
    db = AsyncMock()

    with pytest.raises(EmptyTranscriptError) as exc_info:
        await generate_stage1_note(
            transcript=transcript,
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=db,
        )

    assert exc_info.value.reason == "transcript_too_short"
    assert exc_info.value.transcript_char_count == 6

    fail_loud_registry.get_note_provider.assert_not_called()
    fail_loud_registry.get_note_provider_with_fallback.assert_not_called()

    mock_audit_service.write_event.assert_awaited_once()
    call = mock_audit_service.write_event.call_args
    assert (
        call.kwargs["event_type"]
        == AuditEventType.STAGE1_SKIPPED_LOW_TRANSCRIPT
    )
    assert call.kwargs["reason"] == "transcript_too_short"
    assert call.kwargs["transcript_char_count"] == 6


# ── Whitespace-only segments are treated as empty ─────────────────────────


@pytest.mark.asyncio
async def test_guard_treats_whitespace_only_segments_as_empty(
    mock_audit_service, fail_loud_registry
):
    """A transcript whose segments are all whitespace counts as 0 chars —
    the guard strips whitespace before measuring. Stops the case where
    a silence-padded transcript slips past the threshold."""
    session_id = str(uuid.uuid4())
    transcript = _make_transcript(["   ", "\n\n\n", "\t \t"])
    db = AsyncMock()

    with pytest.raises(EmptyTranscriptError) as exc_info:
        await generate_stage1_note(
            transcript=transcript,
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=db,
        )

    # Stripped char count is 0, which is < threshold → low-transcript branch.
    assert exc_info.value.reason == "transcript_too_short"
    assert exc_info.value.transcript_char_count == 0

    fail_loud_registry.get_note_provider.assert_not_called()


# ── Above-threshold transcript NEVER trips the guard ──────────────────────


@pytest.mark.asyncio
async def test_guard_does_not_fire_for_healthy_transcript():
    """A normal transcript passes the guard and the provider IS called.

    Sanity check: the guard's contract is "no provider call when
    transcript is empty", not "no provider call ever". Mock out the
    provider chain to confirm the happy path still runs.
    """
    session_id = str(uuid.uuid4())
    # 50 chars total, comfortably above the default 20.
    long_text = "Patient describes anterior knee pain for two weeks."
    transcript = _make_transcript([long_text])
    db = AsyncMock()

    # Stub provider returns a minimal valid Note so we can assert it
    # was actually called (vs. the fail-loud fixture above).
    from app.core.types import Note, NoteSection

    stub_note = Note(
        session_id=session_id,
        stage=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[NoteSection(id="chief_complaint", status="not_captured")],
    )
    stub_provider = MagicMock()
    stub_provider.generate_note = AsyncMock(return_value=stub_note)

    fake_registry = MagicMock()
    fake_registry.get_note_provider_with_fallback = MagicMock(
        return_value=stub_provider
    )

    audit_mock = MagicMock()
    audit_mock.write_event = AsyncMock()

    with (
        patch(
            "app.modules.note_gen.service.get_registry",
            return_value=fake_registry,
        ),
        patch(
            "app.modules.note_gen.service.get_audit_log_service",
            return_value=audit_mock,
        ),
        patch(
            "app.modules.note_gen.service.assemble_prompt_for_session",
            new_callable=AsyncMock,
            return_value="stub system prompt",
        ),
        patch(
            "app.modules.note_gen.service._load_prior_context_block",
            new_callable=AsyncMock,
            return_value=(None, ""),
        ),
        patch(
            "app.modules.note_gen.service.critique_note",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.note_gen.service._record_provider_usage",
            new_callable=AsyncMock,
        ),
    ):
        # No EmptyTranscriptError → guard let it through.
        result = await generate_stage1_note(
            transcript=transcript,
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=db,
        )

    # Provider WAS called (not the fail-loud one above).
    stub_provider.generate_note.assert_awaited_once()
    assert result.session_id == session_id
