"""Tests for the clinician-scoped discard-session route.

Covers the two things that matter for a destructive, owner-only endpoint:
ownership is enforced (you can't delete someone else's session), and a
successful delete is recorded with a ``session_discarded`` audit event.
DB access is mocked (unit-level), matching the project's other route tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import sessions as sessions_route
from app.core.audit_events import AuditEventType
from app.core.types import SessionState


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    # Every delete() returns a result whose rowcount delete_session reads.
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _session(clinician_id: uuid.UUID,
             state: SessionState = SessionState.PROCESSING_STAGE1) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.clinician_id = clinician_id
    s.state = state
    return s


class TestDiscardSession:
    @pytest.mark.asyncio
    async def test_owner_discards_commits_and_audits(self):
        cid = uuid.uuid4()
        session = _session(cid)
        db = _mock_db()
        user = MagicMock()
        user.user_id = cid

        with patch.object(sessions_route, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(sessions_route, "write_audit",
                          AsyncMock()) as audit:
            result = await sessions_route.discard_session_route(
                session.id, user=user, db=db
            )

        assert result is None  # 204 No Content
        db.commit.assert_awaited()  # committed before auditing
        audit.assert_awaited_once()
        args, kwargs = audit.call_args
        assert args[1] == AuditEventType.SESSION_DISCARDED
        assert kwargs["prior_state"] == session.state.value

    @pytest.mark.asyncio
    async def test_non_owner_gets_404_and_nothing_deleted(self):
        session = _session(uuid.uuid4())  # owned by another clinician
        db = _mock_db()
        user = MagicMock()
        user.user_id = uuid.uuid4()  # not the owner

        with patch.object(sessions_route, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(sessions_route, "write_audit",
                          AsyncMock()) as audit:
            with pytest.raises(HTTPException) as exc:
                await sessions_route.discard_session_route(
                    session.id, user=user, db=db
                )

        assert exc.value.status_code == 404
        db.commit.assert_not_awaited()
        db.execute.assert_not_awaited()  # no delete attempted
        audit.assert_not_awaited()
