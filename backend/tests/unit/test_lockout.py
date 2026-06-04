"""Unit tests for ``app.modules.auth.lockout`` (AUTH-PIVOT-BACKEND)."""

from __future__ import annotations

from datetime import timedelta

from app.core.clock import utcnow
from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth import lockout


def _new_user() -> UserModel:
    return UserModel(
        email="x@y.z",
        password_hash="",
        full_name="",
        role=UserRole.CLINICIAN,
        failed_login_count=0,
    )


def test_fresh_user_is_not_locked() -> None:
    user = _new_user()
    assert lockout.is_locked(user) is False


def test_five_failures_locks() -> None:
    user = _new_user()
    for i in range(lockout.MAX_FAILED_ATTEMPTS - 1):
        crossed = lockout.record_failure(user)
        assert crossed is False, f"crossed at attempt {i}"
    crossed = lockout.record_failure(user)
    assert crossed is True
    assert lockout.is_locked(user) is True
    assert user.failed_login_count == lockout.MAX_FAILED_ATTEMPTS
    assert user.locked_until is not None


def test_successful_login_resets_counter() -> None:
    user = _new_user()
    for _ in range(3):
        lockout.record_failure(user)
    assert user.failed_login_count == 3
    lockout.record_success(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert lockout.is_locked(user) is False


def test_expired_lockout_clears_on_next_failure() -> None:
    """Once locked_until passes, the next failure starts a fresh window."""
    user = _new_user()
    user.failed_login_count = lockout.MAX_FAILED_ATTEMPTS
    user.locked_until = utcnow() - timedelta(minutes=1)

    # Lockout has expired — is_locked returns False.
    assert lockout.is_locked(user) is False

    crossed = lockout.record_failure(user)
    # Fresh window — only 1 failure on the books, not at threshold.
    assert crossed is False
    assert user.failed_login_count == 1
    assert user.locked_until is None


def test_lockout_duration_is_fifteen_minutes() -> None:
    user = _new_user()
    for _ in range(lockout.MAX_FAILED_ATTEMPTS):
        lockout.record_failure(user)
    assert user.locked_until is not None
    delta = user.locked_until - utcnow()
    # Allow a small timing slop — the test reads the clock twice.
    assert lockout.LOCKOUT_DURATION - timedelta(seconds=1) <= delta
    assert delta <= lockout.LOCKOUT_DURATION + timedelta(seconds=1)


def test_lockout_persists_until_expiry() -> None:
    user = _new_user()
    for _ in range(lockout.MAX_FAILED_ATTEMPTS):
        lockout.record_failure(user)
    assert lockout.is_locked(user) is True

    # Pretend we waited a moment but not long enough.
    user.locked_until = utcnow() + timedelta(seconds=30)
    assert lockout.is_locked(user) is True
