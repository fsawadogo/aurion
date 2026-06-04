"""Account-lockout policy (AUTH-PIVOT-BACKEND).

5 failed login attempts in a row → 15-minute lockout. Counter resets
on a successful login. The state lives on ``UserModel`` so a restart
doesn't reset attackers; the columns are ``failed_login_count`` +
``locked_until``.

The login endpoint NEVER tells an attacker they're locked. The 401
response shape stays identical regardless of cause. The lockout
itself is observable only through the audit log (LOGIN_LOCKED).
"""

from __future__ import annotations

from datetime import timedelta

from app.core.clock import utcnow
from app.core.models import UserModel

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def is_locked(user: UserModel) -> bool:
    """True if the user has a lockout still in effect.

    A row whose ``locked_until`` is in the past is not "locked" — the
    next failure starts a fresh counter (see ``record_failure``). This
    function answers "should I refuse this login right now?".
    """
    if user.locked_until is None:
        return False
    return user.locked_until > utcnow()


def record_failure(user: UserModel) -> bool:
    """Increment the failure counter. Returns True if THIS failure
    crossed the threshold (so the caller can emit a LOGIN_LOCKED audit
    event exactly once).

    Behaviour:
    * If a previous lockout has expired, the counter resets to 1 — the
      user gets a fresh 5-attempt window.
    * Reaching MAX_FAILED_ATTEMPTS sets ``locked_until`` to ``utcnow +
      LOCKOUT_DURATION`` and returns True.
    """
    now = utcnow()

    # Lockout already expired? Start a fresh window.
    if user.locked_until is not None and user.locked_until <= now:
        user.locked_until = None
        user.failed_login_count = 0

    user.failed_login_count = (user.failed_login_count or 0) + 1

    crossed_threshold = user.failed_login_count >= MAX_FAILED_ATTEMPTS
    if crossed_threshold:
        user.locked_until = now + LOCKOUT_DURATION

    return crossed_threshold


def record_success(user: UserModel) -> None:
    """Clear the failure counter + any lockout. Called on every
    successful password verification (before MFA, but after the
    password gate)."""
    user.failed_login_count = 0
    user.locked_until = None


__all__ = [
    "MAX_FAILED_ATTEMPTS",
    "LOCKOUT_DURATION",
    "is_locked",
    "record_failure",
    "record_success",
]
