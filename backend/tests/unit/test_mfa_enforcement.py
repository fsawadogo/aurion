"""Unit tests for the #397/OV-5 MFA enforcement mechanism (ships dark).

Login gate (AC-1/AC-2): driven through the real `login` handler with the
user lookup + password verify + lockout mocked, so the branch logic is
exercised without Postgres (CI runs unit-only).

Admin toggle (AC-3): the repo records mfa_required in the USER_UPDATED
changes dict.

Token isolation: an enrollment token and a challenge token are distinct
types so neither replays as the other.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import auth as auth_mod
from app.api.v1.auth import (
    LoginEnrollmentRequiredResponse,
    LoginMfaRequiredResponse,
    LoginRequest,
)
from app.modules.auth import users_repository as users_repo


def _user(*, mfa_required: bool, enrolled: bool) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "doc@aurionclinical.com"
    u.password_hash = "hash"
    u.is_active = True
    u.mfa_required = mfa_required
    u.mfa_enrolled_at = datetime.now(timezone.utc) if enrolled else None
    return u


async def _run_login(user) -> object:
    body = LoginRequest(email=user.email, password="Sup3rSecret!")
    request = MagicMock()
    with patch.object(auth_mod, "_find_user_by_email", AsyncMock(return_value=user)), \
         patch.object(auth_mod, "verify_password", return_value=True), \
         patch.object(auth_mod.lockout, "is_locked", return_value=False), \
         patch.object(auth_mod.lockout, "record_success", MagicMock()), \
         patch.object(
             auth_mod, "_issue_tokens_and_persist",
             AsyncMock(return_value={"access_token": "tok", "token_type": "bearer"}),
         ):
        return await login_call(body, request)


async def login_call(body, request):
    # The handler takes (body, request, db); db is unused on the gate paths.
    return await auth_mod.login(body, request, db=AsyncMock())


@pytest.mark.asyncio
async def test_required_but_not_enrolled_blocks_with_enrollment(monkeypatch) -> None:
    """AC-1: mfa_required=True + not enrolled → enrollment-required, no tokens."""
    result = await _run_login(_user(mfa_required=True, enrolled=False))
    assert isinstance(result, LoginEnrollmentRequiredResponse)
    assert result.enroll_required is True
    assert result.mfa_enrollment_token
    assert "access_token" not in getattr(result, "__dict__", {})


@pytest.mark.asyncio
async def test_default_off_is_unchanged_login(monkeypatch) -> None:
    """AC-2: mfa_required=False (the default) + not enrolled → normal
    token issue (ships dark — zero behavior change)."""
    result = await _run_login(_user(mfa_required=False, enrolled=False))
    assert result == {"access_token": "tok", "token_type": "bearer"}


@pytest.mark.asyncio
async def test_enrolled_user_still_gets_mfa_challenge(monkeypatch) -> None:
    """Enrolled users keep the existing challenge path whether or not
    mfa_required is set — enforcement doesn't double-prompt."""
    result = await _run_login(_user(mfa_required=True, enrolled=True))
    assert isinstance(result, LoginMfaRequiredResponse)
    assert result.mfa_challenge_token


# ── AC-3: admin toggle records the change ────────────────────────────────────


@pytest.mark.asyncio
async def test_update_user_tracks_mfa_required_change() -> None:
    db = AsyncMock()
    db.flush = AsyncMock()
    user = MagicMock()
    user.full_name = "Dr A"
    user.mfa_required = False
    with patch.object(users_repo, "get_user", AsyncMock(return_value=user)):
        updated, changes = await users_repo.update_user(
            db, uuid.uuid4(), mfa_required=True
        )
    assert user.mfa_required is True
    assert changes["mfa_required"] == {"previous": False, "new": True}
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_update_user_no_change_when_same() -> None:
    db = AsyncMock()
    db.flush = AsyncMock()
    user = MagicMock()
    user.mfa_required = True
    with patch.object(users_repo, "get_user", AsyncMock(return_value=user)):
        _updated, changes = await users_repo.update_user(
            db, uuid.uuid4(), mfa_required=True
        )
    assert "mfa_required" not in changes


# ── Token type isolation ─────────────────────────────────────────────────────


def test_enrollment_and_challenge_tokens_are_distinct_types() -> None:
    # The codebase signs with python-jose (jose.jwt), not PyJWT — read the
    # claims via jose's unverified reader to inspect the `type` claim.
    from jose import jwt

    from app.modules.auth.jwt_tokens import (
        mint_mfa_challenge_token,
        mint_mfa_enrollment_token,
    )

    uid = uuid.uuid4()
    enroll = mint_mfa_enrollment_token(user_id=uid, email="d@a.com")
    challenge = mint_mfa_challenge_token(user_id=uid, email="d@a.com")
    enroll_claims = jwt.get_unverified_claims(enroll)
    challenge_claims = jwt.get_unverified_claims(challenge)
    assert enroll_claims["type"] == "mfa_enrollment"
    assert challenge_claims["type"] == "mfa_challenge"
    assert enroll_claims["type"] != challenge_claims["type"]


def test_verify_enrollment_token_round_trip_and_cross_type_rejection() -> None:
    """The enrollment verifier accepts its own token and REJECTS a
    challenge token (and vice versa) — the security crux: a token scoped
    to one ceremony can't authorize the other."""
    from app.modules.auth.jwt_tokens import (
        mint_mfa_challenge_token,
        mint_mfa_enrollment_token,
        verify_mfa_challenge_token,
        verify_mfa_enrollment_token,
    )

    uid = uuid.uuid4()
    enroll = mint_mfa_enrollment_token(user_id=uid, email="d@a.com")
    challenge = mint_mfa_challenge_token(user_id=uid, email="d@a.com")

    # Each verifier accepts only its own type.
    assert verify_mfa_enrollment_token(enroll) is not None
    assert verify_mfa_enrollment_token(enroll).user_id == uid
    assert verify_mfa_challenge_token(challenge) is not None

    # Cross-replay is rejected both directions.
    assert verify_mfa_enrollment_token(challenge) is None
    assert verify_mfa_challenge_token(enroll) is None
    # Garbage is rejected.
    assert verify_mfa_enrollment_token("not.a.jwt") is None
