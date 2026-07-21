"""EVAL-1 — the eval-lab "runs" endpoint returns every note version of a
session as a comparable run, with deterministic metrics, EVAL_TEAM/ADMIN
gated and assignee-scoped."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.admin import eval as eval_api
from app.core.types import UserRole


def _note_json(n_claims: int, grounded: bool) -> str:
    """A note with `n_claims` claims in one populated section. When grounded,
    each claim cites seg_0 (a real transcript id); else an unknown id."""
    src = "seg_0" if grounded else "seg_missing"
    return json.dumps(
        {
            "session_id": "s1",
            "stage": 1,
            "version": 1,
            "provider_used": "anthropic",
            "specialty": "general",
            "sections": [
                {
                    "id": "hpi",
                    "title": "HPI",
                    "status": "populated",
                    "claims": [
                        {
                            "id": f"c{i}",
                            "text": "x",
                            "source_type": "transcript",
                            "source_id": src,
                        }
                        for i in range(n_claims)
                    ],
                }
            ],
        }
    )


def _version(version: int, *, n_claims: int, grounded: bool, stage: int = 1):
    return SimpleNamespace(
        version=version,
        stage=stage,
        provider_used="anthropic",
        completeness_score=1.0,
        is_approved=False,
        created_at=None,
        content=_note_json(n_claims, grounded),
    )


def _transcript_row():
    return SimpleNamespace(
        transcript_json=json.dumps(
            {
                "session_id": "s1",
                "provider_used": "whisper",
                "segments": [
                    {"id": "seg_0", "start_ms": 0, "end_ms": 10, "text": "hi"}
                ],
            }
        )
    )


def _db(session_row, transcript_row):
    """`db.get` returns the session for SessionModel, transcript for
    TranscriptModel (the endpoint calls it once each, in that order)."""
    from app.core.models import SessionModel, TranscriptModel

    async def _get(model, _id):
        if model is SessionModel:
            return session_row
        if model is TranscriptModel:
            return transcript_row
        return None

    return SimpleNamespace(get=AsyncMock(side_effect=_get))


ADMIN = SimpleNamespace(user_id=uuid.uuid4(), role=UserRole.ADMIN)


@pytest.mark.asyncio
async def test_returns_all_versions_with_metrics():
    session = SimpleNamespace(id=uuid.uuid4())
    versions = [
        _version(1, n_claims=2, grounded=True),
        _version(2, n_claims=5, grounded=False),
    ]
    with (
        patch.object(eval_api.eval_repo, "get_assignment", AsyncMock(return_value=None)),
        patch.object(eval_api.note_repo, "get_all_versions", AsyncMock(return_value=versions)),
    ):
        runs = await eval_api.get_eval_session_runs(
            str(session.id), user=ADMIN, db=_db(session, _transcript_row())
        )

    assert [r.version for r in runs] == [1, 2]
    # v1: 2 claims, both cite the real seg_0 → fully grounded.
    assert runs[0].metrics["total_claims"] == 2
    assert runs[0].metrics["grounding_rate"] == 1.0
    # v2: 5 claims citing an unknown id → 0 grounded, and the run carries the
    # note so the UI can render + diff it.
    assert runs[1].metrics["total_claims"] == 5
    assert runs[1].metrics["grounding_rate"] == 0.0
    assert runs[1].note_sections[0]["id"] == "hpi"
    # Provenance is null until the migration lands — must not crash.
    assert runs[0].settings_snapshot is None


@pytest.mark.asyncio
async def test_missing_transcript_degrades_not_crashes():
    """No transcript → no verifiable ids → grounding 0, but the runs still
    return (never a 500)."""
    session = SimpleNamespace(id=uuid.uuid4())
    with (
        patch.object(eval_api.eval_repo, "get_assignment", AsyncMock(return_value=None)),
        patch.object(
            eval_api.note_repo, "get_all_versions",
            AsyncMock(return_value=[_version(1, n_claims=3, grounded=True)]),
        ),
    ):
        runs = await eval_api.get_eval_session_runs(
            str(session.id), user=ADMIN, db=_db(session, None)
        )
    assert runs[0].metrics["total_claims"] == 3
    assert runs[0].metrics["grounding_rate"] == 0.0  # nothing verifiable


@pytest.mark.asyncio
async def test_unknown_session_404():
    with patch.object(
        eval_api.eval_repo, "get_assignment", AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as exc:
            await eval_api.get_eval_session_runs(
                str(uuid.uuid4()), user=ADMIN, db=_db(None, None)
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_eval_team_non_assignee_404():
    """EVAL_TEAM sees only sessions assigned to them — an unassigned session is
    404, same as the triad route."""
    session = SimpleNamespace(id=uuid.uuid4())
    reviewer = SimpleNamespace(user_id=uuid.uuid4(), role=UserRole.EVAL_TEAM)
    with (
        patch.object(eval_api.eval_repo, "get_assignment", AsyncMock(return_value=None)),
        patch.object(eval_api.note_repo, "get_all_versions", AsyncMock(return_value=[])),
    ):
        with pytest.raises(HTTPException) as exc:
            await eval_api.get_eval_session_runs(
                str(session.id), user=reviewer, db=_db(session, None)
            )
    assert exc.value.status_code == 404
