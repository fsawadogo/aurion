"""Tests for the ADMIN delete-any-session route (Captured Media admin action).

The admin counterpart to the owner-scoped clinician discard: an ADMIN can
hard-delete ANY clinician's session. Covers that it deletes + commits, purges
the raw S3 media, and records an append-only ``admin_session_deleted`` audit
event carrying the prior state + the target clinician. DB + media are mocked
(unit-level), matching the project's other route tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.admin import sessions as admin_sessions
from app.core.audit_events import AuditEventType
from app.core.types import SessionState


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _session(state: SessionState = SessionState.AWAITING_REVIEW) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.clinician_id = uuid.uuid4()  # a DIFFERENT clinician than the admin
    s.state = state
    return s


class TestAdminDeleteSession:
    @pytest.mark.asyncio
    async def test_admin_deletes_any_session_commits_purges_audits(self):
        session = _session()
        db = _mock_db()
        admin = MagicMock(user_id=uuid.uuid4())  # not the session owner

        with patch.object(admin_sessions, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(admin_sessions, "delete_session",
                          AsyncMock(return_value={})) as del_sess, \
             patch.object(admin_sessions, "purge_session_media",
                          AsyncMock()) as purge, \
             patch.object(admin_sessions, "write_audit",
                          AsyncMock()) as audit:
            result = await admin_sessions.admin_delete_session(
                session.id, actor=admin, db=db
            )

        assert result is None  # 204 No Content
        del_sess.assert_awaited_once()           # DB rows deleted
        db.commit.assert_awaited()               # committed before media purge + audit
        purge.assert_awaited_once_with(str(session.id))  # S3 media purged
        audit.assert_awaited_once()
        args, kwargs = audit.call_args
        assert args[0] == session.id
        assert args[1] == AuditEventType.ADMIN_SESSION_DELETED
        assert kwargs["prior_state"] == SessionState.AWAITING_REVIEW.value
        assert kwargs["target_clinician_id"] == str(session.clinician_id)

    @pytest.mark.asyncio
    async def test_fetches_via_non_owner_helper(self):
        """Uses get_session_or_404 (any session) — NOT the owner-scoped
        helper — so an admin can reach a session they don't own."""
        session = _session()
        db = _mock_db()
        with patch.object(admin_sessions, "get_session_or_404",
                          AsyncMock(return_value=session)) as getter, \
             patch.object(admin_sessions, "delete_session", AsyncMock(return_value={})), \
             patch.object(admin_sessions, "purge_session_media", AsyncMock()), \
             patch.object(admin_sessions, "write_audit", AsyncMock()):
            await admin_sessions.admin_delete_session(
                session.id, actor=MagicMock(user_id=uuid.uuid4()), db=db
            )
        getter.assert_awaited_once()
        assert not hasattr(admin_sessions, "get_owned_session_or_404")


class TestAuditEventRegistered:
    def test_admin_session_deleted_allowed_kwargs(self):
        from app.core.audit_events import ALLOWED_AUDIT_KWARGS
        keys = ALLOWED_AUDIT_KWARGS[AuditEventType.ADMIN_SESSION_DELETED]
        assert keys == frozenset({"prior_state", "target_clinician_id"})
