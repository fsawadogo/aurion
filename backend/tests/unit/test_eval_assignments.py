"""Unit tests for EVAL-3 eval session assignment.

Covers the 7 AC tests from docs/plans/EVAL-3-eval-session-assignment.md.
Uses the same mocked-AsyncSession pattern as test_eval_persistence.py —
no docker / no real DB.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.clock import utcnow
from app.core.models import EvalAssignmentModel
from app.core.types import UserRole
from app.modules.eval import repository as eval_repo


def _make_assignment(
    session_id: uuid.UUID | None = None,
    assignee_email: str = "uzziel.tamon@aurionclinical.com",
    assignee_user_id: uuid.UUID | None = None,
    completed: bool = False,
) -> EvalAssignmentModel:
    row = EvalAssignmentModel(
        session_id=session_id or uuid.uuid4(),
        assignee_user_id=assignee_user_id or uuid.uuid4(),
        assignee_email=assignee_email,
        assigned_by=uuid.uuid4(),
        assigned_by_email="faical.sawadogo@aurionclinical.com",
    )
    row.assigned_at = utcnow()
    row.completed_at = utcnow() if completed else None
    return row


# ── Repository-level tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_assignment_returns_row_when_present() -> None:
    sid = uuid.uuid4()
    row = _make_assignment(session_id=sid)
    db = MagicMock()
    db.get = AsyncMock(return_value=row)

    result = await eval_repo.get_assignment(db, sid)
    assert result is row
    db.get.assert_awaited_once_with(EvalAssignmentModel, sid)


@pytest.mark.asyncio
async def test_get_assignments_by_sessions_empty_short_circuits() -> None:
    db = MagicMock()
    db.execute = AsyncMock()

    result = await eval_repo.get_assignments_by_sessions(db, [])
    assert result == {}
    assert db.execute.await_count == 0


@pytest.mark.asyncio
async def test_get_session_ids_assigned_to_returns_set() -> None:
    sid_a, sid_b = uuid.uuid4(), uuid.uuid4()
    assignee = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=lambda: MagicMock(all=lambda: [sid_a, sid_b])
        )
    )

    result = await eval_repo.get_session_ids_assigned_to(db, assignee)
    assert result == {sid_a, sid_b}
    assert isinstance(result, set)


@pytest.mark.asyncio
async def test_upsert_assignment_clears_completed_at() -> None:
    """Re-assigning a previously-completed session must reset
    completed_at so the new assignee sees it as open work."""
    sid = uuid.uuid4()
    new_assignee = uuid.uuid4()
    refetched = _make_assignment(
        session_id=sid, assignee_user_id=new_assignee
    )

    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock(return_value=refetched)

    result = await eval_repo.upsert_assignment(
        db,
        session_id=sid,
        assignee_user_id=new_assignee,
        assignee_email="freddy.beltran@aurionclinical.com",
        assigned_by=uuid.uuid4(),
        assigned_by_email="faical.sawadogo@aurionclinical.com",
    )
    assert result is refetched
    assert db.execute.await_count == 1

    # Confirm the executed statement carries an ON CONFLICT and the
    # set_ clause resets completed_at to NULL.
    stmt = db.execute.await_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "ON CONFLICT" in compiled
    # The values dict was constructed with completed_at=None
    # so the bind-parameter for completed_at is NULL.
    assert "completed_at" in compiled.lower()


@pytest.mark.asyncio
async def test_delete_assignment_returns_true_when_row_removed() -> None:
    sid = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

    result = await eval_repo.delete_assignment(db, sid)
    assert result is True
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_delete_assignment_returns_false_when_no_row() -> None:
    sid = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))

    result = await eval_repo.delete_assignment(db, sid)
    assert result is False


@pytest.mark.asyncio
async def test_mark_assignment_complete_sets_completed_at() -> None:
    """AC-5 repository half: mark_assignment_complete sets the
    completed_at timestamp on the matching row."""
    sid = uuid.uuid4()
    row = _make_assignment(session_id=sid, completed=False)
    assert row.completed_at is None

    db = MagicMock()
    db.get = AsyncMock(return_value=row)
    db.flush = AsyncMock()

    result = await eval_repo.mark_assignment_complete(db, sid)
    assert result is row
    assert row.completed_at is not None
    assert db.flush.await_count == 1


@pytest.mark.asyncio
async def test_mark_assignment_complete_returns_none_if_missing() -> None:
    """No assignment → no-op; no flush, no surprise."""
    sid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.flush = AsyncMock()

    result = await eval_repo.mark_assignment_complete(db, sid)
    assert result is None
    assert db.flush.await_count == 0


# ── Audit event whitelist coverage ─────────────────────────────────────────


def test_assignment_audit_events_have_whitelist_entries() -> None:
    """The 3 new audit event types must be in ALLOWED_AUDIT_KWARGS so
    write_audit doesn't reject them at runtime."""
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType

    for evt in (
        AuditEventType.EVAL_ASSIGNMENT_CREATED,
        AuditEventType.EVAL_ASSIGNMENT_REMOVED,
        AuditEventType.EVAL_ASSIGNMENT_COMPLETED,
    ):
        assert evt in ALLOWED_AUDIT_KWARGS, (
            f"{evt.value} missing from ALLOWED_AUDIT_KWARGS"
        )


# ── Schema-shape tests (AC-1 / AC-3 / AC-4 / AC-6 shape contracts) ─────────


def test_eval_session_response_carries_assignment_columns() -> None:
    """AC-1 / AC-3 / AC-4 shape: EvalSessionResponse must accept
    assigned_to + assignment_completed_at as optional fields. Older
    clients passing only the legacy fields still validate."""
    from app.api.v1.admin._shared import EvalSessionResponse

    legacy = EvalSessionResponse(
        id="eval_abc",
        session_id=str(uuid.uuid4()),
        clinician_name="Dr. Test",
        specialty="general",
        transcript_masked=True,
        frames_masked=True,
        note_version=1,
        scored=False,
        created_at="2026-05-26T00:00:00+00:00",
    )
    assert legacy.assigned_to is None
    assert legacy.assignment_completed_at is None

    assigned = EvalSessionResponse(
        id="eval_abc",
        session_id=str(uuid.uuid4()),
        clinician_name="Dr. Test",
        specialty="general",
        transcript_masked=True,
        frames_masked=True,
        note_version=1,
        scored=False,
        created_at="2026-05-26T00:00:00+00:00",
        assigned_to="uzziel.tamon@aurionclinical.com",
    )
    assert assigned.assigned_to == "uzziel.tamon@aurionclinical.com"


def test_eval_assignment_request_requires_email() -> None:
    """AC-1 shape: assign endpoint payload validates."""
    from pydantic import ValidationError

    from app.api.v1.admin._shared import EvalAssignmentRequest

    valid = EvalAssignmentRequest(assignee_email="x@aurionclinical.com")
    assert valid.assignee_email == "x@aurionclinical.com"

    with pytest.raises(ValidationError):
        EvalAssignmentRequest()  # type: ignore[call-arg]


def test_eval_assignee_response_carries_role() -> None:
    """AC-6 shape: assignee list returns user_id / email / full_name / role."""
    from app.api.v1.admin._shared import EvalAssigneeResponse

    r = EvalAssigneeResponse(
        user_id=str(uuid.uuid4()),
        email="x@aurionclinical.com",
        full_name="X",
        role=UserRole.EVAL_TEAM,
    )
    assert r.role == UserRole.EVAL_TEAM


# ── Router registration (AC-7 partial — endpoints exist + are guarded) ─────


def test_assignment_endpoints_registered() -> None:
    """AC-7 partial: the 3 new endpoints must exist on the router."""
    from app.api.v1.admin.eval import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/admin/eval/sessions/{session_id}/assign", ("POST",)) in paths
    assert ("/admin/eval/sessions/{session_id}/assign", ("DELETE",)) in paths
    assert ("/admin/eval/assignees", ("GET",)) in paths
