"""Unit tests for the persistent eval scores layer (B-08)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.admin import eval as admin_eval
from app.core.clock import utcnow
from app.core.models import EvalScoreModel
from app.modules.eval import repository as eval_repo


def _make_score(
    session_id: uuid.UUID | None = None,
    overall: float = 88.5,
    scored_by: str = "eval@aurionclinical.com",
) -> EvalScoreModel:
    row = EvalScoreModel(
        session_id=session_id or uuid.uuid4(),
        transcript_accuracy=90.0,
        citation_correctness=92.0,
        descriptive_mode_compliance=83.5,
        overall=overall,
        notes="Looks great.",
        scored_by=scored_by,
    )
    row.scored_at = utcnow()
    return row


def test_eval_scores_dict_removed() -> None:
    """Regression guard — the in-memory _EVAL_SCORES dict must stay gone."""
    assert not hasattr(admin_eval, "_EVAL_SCORES"), (
        "_EVAL_SCORES dict was reintroduced — eval scores must persist via the DB."
    )


def test_score_payload_serializes_full_shape() -> None:
    row = _make_score()
    payload = admin_eval._score_payload(row)
    assert payload["transcript_accuracy"] == 90.0
    assert payload["citation_correctness"] == 92.0
    assert payload["descriptive_mode_compliance"] == 83.5
    assert payload["overall"] == 88.5
    assert payload["notes"] == "Looks great."
    assert payload["scored_by"] == "eval@aurionclinical.com"
    assert payload["scored_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_get_score_returns_row_when_present() -> None:
    sid = uuid.uuid4()
    row = _make_score(session_id=sid)

    db = MagicMock()
    db.get = AsyncMock(return_value=row)

    result = await eval_repo.get_score(db, sid)
    assert result is row
    db.get.assert_awaited_once_with(EvalScoreModel, sid)


@pytest.mark.asyncio
async def test_get_score_accepts_string_session_id() -> None:
    sid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=None)

    await eval_repo.get_score(db, str(sid))
    db.get.assert_awaited_once_with(EvalScoreModel, sid)


@pytest.mark.asyncio
async def test_get_scores_by_sessions_returns_empty_for_no_ids() -> None:
    db = MagicMock()
    db.execute = AsyncMock()  # should not be called

    result = await eval_repo.get_scores_by_sessions(db, [])
    assert result == {}
    assert db.execute.await_count == 0


@pytest.mark.asyncio
async def test_get_scores_by_sessions_keys_by_session_id() -> None:
    sid_a = uuid.uuid4()
    sid_b = uuid.uuid4()
    row_a = _make_score(session_id=sid_a)
    row_b = _make_score(session_id=sid_b)

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [row_a, row_b]))
    )

    result = await eval_repo.get_scores_by_sessions(db, [sid_a, sid_b])
    assert result == {sid_a: row_a, sid_b: row_b}


@pytest.mark.asyncio
async def test_upsert_score_uses_on_conflict_then_refetches() -> None:
    sid = uuid.uuid4()
    refetched = _make_score(session_id=sid, overall=77.0)

    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock(return_value=refetched)

    result = await eval_repo.upsert_score(
        db,
        session_id=sid,
        transcript_accuracy=70.0,
        citation_correctness=80.0,
        descriptive_mode_compliance=81.0,
        overall=77.0,
        notes="Decent first pass.",
        scored_by="eval@aurionclinical.com",
    )
    assert result is refetched
    assert db.execute.await_count == 1
    db.get.assert_awaited_once_with(EvalScoreModel, sid)

    # Confirm the executed statement carries an ON CONFLICT clause; we
    # look at the compiled SQL rather than the statement-object internals
    # so this stays stable across SQLAlchemy patch releases.
    stmt = db.execute.await_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "ON CONFLICT" in compiled.upper()
