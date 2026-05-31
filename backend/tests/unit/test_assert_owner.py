"""Row-level ownership gate (``assert_owner``) regression test.

Locks in the four cases that matter:
  * Owner clinician sees their own session.
  * Non-owner clinician gets 404 (not 403) — leaking the existence of
    another clinician's session is itself a soft PHI disclosure.
  * Admin and compliance bypass the row scope and see any session.
  * Eval team does NOT bypass — they need explicit eval assignments,
    not arbitrary access.

If anyone changes the bypass-role set or the 404-for-clinician behavior,
this test should be the first thing to scream.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.v1._helpers import assert_owner
from app.core.models import SessionModel
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser


def _session(clinician_id: uuid.UUID) -> SessionModel:
    """Build a minimally-populated SessionModel — we only touch clinician_id
    in assert_owner, so the other columns can be defaults."""
    s = SessionModel()
    s.id = uuid.uuid4()
    s.clinician_id = clinician_id
    return s


def _user(user_id: uuid.UUID, role: UserRole) -> CurrentUser:
    return CurrentUser(user_id=user_id, role=role, email="t@t")


def test_owner_clinician_passes() -> None:
    owner = uuid.uuid4()
    session = _session(owner)
    user = _user(owner, UserRole.CLINICIAN)

    # No exception — the assertion silently returns.
    assert_owner(session, user)


def test_non_owner_clinician_404_not_403() -> None:
    """Clinicians get a 404 rather than 403 when peeking at another
    clinician's session id — keeps the existence of the row private."""
    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    session = _session(owner)
    user = _user(intruder, UserRole.CLINICIAN)

    with pytest.raises(HTTPException) as exc_info:
        assert_owner(session, user)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Session not found"


def test_admin_bypasses_row_scope() -> None:
    """Admin sees any session — needed for support paths."""
    owner = uuid.uuid4()
    session = _session(owner)
    user = _user(uuid.uuid4(), UserRole.ADMIN)

    assert_owner(session, user)  # no exception


def test_compliance_officer_bypasses_row_scope() -> None:
    """Compliance reads everyone's audit trail; bypass is required."""
    owner = uuid.uuid4()
    session = _session(owner)
    user = _user(uuid.uuid4(), UserRole.COMPLIANCE_OFFICER)

    assert_owner(session, user)  # no exception


def test_eval_team_does_NOT_bypass() -> None:
    """Eval team should only see explicitly-assigned eval rows. If they
    hit a /sessions/{id} or /notes/{id} directly with somebody else's
    session id, we 403 them — not 404, because they're authenticated to
    some scope and the misuse is worth surfacing."""
    owner = uuid.uuid4()
    session = _session(owner)
    user = _user(uuid.uuid4(), UserRole.EVAL_TEAM)

    with pytest.raises(HTTPException) as exc_info:
        assert_owner(session, user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Not session owner"
