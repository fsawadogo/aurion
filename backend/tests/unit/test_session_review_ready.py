"""`stage2_review_ready` — the display-only "Stage 2 done, awaiting your
approval" signal on the session response.

A session genuinely rests in PROCESSING_STAGE2 between Stage 2 completing and
the physician's manual final approval. This flag lets clients render "Ready
for review" instead of "Processing/Enriching" for that window — the case that
left two web-imported sessions looking stuck for days. It is NOT a state
change: the session stays PROCESSING_STAGE2 and approval stays human.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.sessions import _review_ready_session_ids, _to_response
from app.core.types import SessionState


def _session(state: str, sid: uuid.UUID | None = None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=sid or uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        specialty="orthopedic_surgery",
        state=state,
        encounter_type="doctor_patient",
        capture_mode="multimodal",
        import_source="video_upload",
        external_reference_id_encrypted=None,
        provider_overrides=None,
        participants_json=None,
        created_at=now,
        updated_at=now,
    )


def _db_with_jobs(rows):
    """rows: list of (session_id, status, created_at)."""
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


# ── _to_response field ───────────────────────────────────────────────────────


def test_to_response_defaults_review_ready_false() -> None:
    resp = _to_response(_session(SessionState.PROCESSING_STAGE2.value))
    assert resp.stage2_review_ready is False


def test_to_response_sets_review_ready_when_passed() -> None:
    resp = _to_response(
        _session(SessionState.PROCESSING_STAGE2.value), review_ready=True
    )
    assert resp.stage2_review_ready is True


# ── _review_ready_session_ids ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completed_stage2_job_in_processing_state_is_ready() -> None:
    s = _session(SessionState.PROCESSING_STAGE2.value)
    now = datetime.now(timezone.utc)
    db = _db_with_jobs([(s.id, "completed", now)])
    ready = await _review_ready_session_ids(db, [s])
    assert s.id in ready


@pytest.mark.asyncio
async def test_running_stage2_job_is_not_ready() -> None:
    s = _session(SessionState.PROCESSING_STAGE2.value)
    now = datetime.now(timezone.utc)
    db = _db_with_jobs([(s.id, "running", now)])
    ready = await _review_ready_session_ids(db, [s])
    assert s.id not in ready


@pytest.mark.asyncio
async def test_latest_job_wins_over_older_completed() -> None:
    """A newer running job (e.g. a re-run) overrides an older completed one —
    the rows come back created_at DESC, so the first per session is latest."""
    s = _session(SessionState.PROCESSING_STAGE2.value)
    newer = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
    older = datetime(2026, 6, 20, 11, 0, tzinfo=timezone.utc)
    db = _db_with_jobs([(s.id, "running", newer), (s.id, "completed", older)])
    ready = await _review_ready_session_ids(db, [s])
    assert s.id not in ready


@pytest.mark.asyncio
async def test_non_processing_state_is_never_a_candidate() -> None:
    """An AWAITING_REVIEW session isn't queried at all (no Stage 2 yet)."""
    s = _session(SessionState.AWAITING_REVIEW.value)
    db = _db_with_jobs([])
    ready = await _review_ready_session_ids(db, [s])
    assert ready == set()
    db.execute.assert_not_called()  # short-circuits with no candidates


@pytest.mark.asyncio
async def test_review_complete_session_not_ready() -> None:
    s = _session(SessionState.REVIEW_COMPLETE.value)
    db = _db_with_jobs([])
    ready = await _review_ready_session_ids(db, [s])
    assert s.id not in ready
