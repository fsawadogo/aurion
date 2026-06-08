# ruff: noqa: F401, F811
"""Integration tests for /api/v1/auth/login (AUTH-PIVOT-BACKEND).

Covers the AC matrix from docs/plans/auth-pivot-backend-jwt.md:
* happy path → access + refresh + user payload
* wrong password → 401 + LOGIN_FAILURE audit; failed_login_count++
* unknown user → 401 (same shape; no LOGIN_FAILURE audit)
* locked user → 401 + LOGIN_LOCKED audit at threshold
* 5th failure → user locked for 15 minutes
* MFA-enrolled user → mfa_required + challenge

The F401 + F811 noqa at the top covers pytest's fixture-injection
pattern: fixtures must be imported (F401-tripping) and they're
referenced as test parameters (F811-tripping). The other Aurion tests
that share fixtures across files use the same noqa pattern.
"""

from __future__ import annotations

import pytest

from app.core.audit_events import AuditEventType
from app.core.types import UserRole

from ._auth_fixtures import (
    PG_OK,
    PG_SKIP_REASON,
    app_client,  # noqa: F401
    db_engine,  # noqa: F401
    db_session,  # noqa: F401
    mock_audit_log,  # noqa: F401
    mock_kms,  # noqa: F401
    seed_user,
)

pytestmark = pytest.mark.skipif(
    not PG_OK,
    reason=(
        "Aurion Postgres not available — start "
        "`docker compose up -d postgres`. "
        f"({PG_SKIP_REASON})"
    ),
)


async def test_login_happy_path(app_client, db_session, mock_audit_log) -> None:
    user_id, email = await seed_user(db_session)
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 1800
    assert body["user"]["user_id"] == str(user_id)
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "CLINICIAN"
    assert body["user"]["mfa_enrolled"] is False

    # LOGIN_SUCCESS + REFRESH_TOKEN_ISSUED both emitted.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.LOGIN_SUCCESS in types
    assert AuditEventType.REFRESH_TOKEN_ISSUED in types


async def test_login_wrong_password_returns_401_and_audits_failure(
    app_client, db_session, mock_audit_log
) -> None:
    user_id, email = await seed_user(db_session)
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WRONG-password-1!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

    events = [
        (c.kwargs["event_type"], c.kwargs)
        for c in mock_audit_log.write_event.call_args_list
    ]
    failures = [k for et, k in events if et == AuditEventType.LOGIN_FAILURE]
    assert len(failures) == 1
    assert failures[0]["target_user_id"] == str(user_id)
    assert failures[0]["reason"] == "bad_password"


async def test_login_unknown_user_returns_same_401_shape(
    app_client, db_session, mock_audit_log
) -> None:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody.never@nowhere.local", "password": "anything"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."
    # No LOGIN_FAILURE row because we don't know the target user_id —
    # the audit-event whitelist requires target_user_id and we won't
    # invent one.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.LOGIN_FAILURE not in types


async def test_login_inactive_user_returns_401(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session, is_active=False)
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."
    # The failure was emitted with reason=inactive — still bounded enum.
    failure_reasons = [
        c.kwargs.get("reason")
        for c in mock_audit_log.write_event.call_args_list
        if c.kwargs["event_type"] == AuditEventType.LOGIN_FAILURE
    ]
    assert failure_reasons == ["inactive"]


async def test_five_failures_locks_user(
    app_client, db_session, mock_audit_log
) -> None:
    from app.core.models import UserModel

    user_id, email = await seed_user(db_session)
    for _ in range(5):
        await app_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WRONG"},
        )

    # LOGIN_LOCKED fired exactly once (only at the threshold).
    locks = [
        c.kwargs
        for c in mock_audit_log.write_event.call_args_list
        if c.kwargs["event_type"] == AuditEventType.LOGIN_LOCKED
    ]
    assert len(locks) == 1
    assert locks[0]["target_user_id"] == str(user_id)
    assert locks[0]["failed_count"] == 5

    # 6th attempt — DISTINCT lockout response, no extra LOGIN_LOCKED audit.
    db_session.expire_all()
    user = await db_session.get(UserModel, user_id)
    assert user is not None
    assert user.locked_until is not None
    assert user.failed_login_count == 5
    locked_until_before = user.locked_until

    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},  # correct now
    )
    # Locked → distinct 429 "too many attempts" even with the right
    # password, so the user knows it's a lockout (not a bad password).
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail != "Invalid email or password."
    assert "Too many failed sign-in attempts" in detail
    assert "minute" in detail

    # The lockout path must NOT extend the lock or bump the counter
    # (no record_failure). Duration + accounting unchanged.
    db_session.expire_all()
    user = await db_session.get(UserModel, user_id)
    assert user is not None
    assert user.failed_login_count == 5
    assert user.locked_until == locked_until_before

    # Still exactly one LOGIN_LOCKED audit — the 6th attempt emitted none.
    locks_after = [
        c.kwargs
        for c in mock_audit_log.write_event.call_args_list
        if c.kwargs["event_type"] == AuditEventType.LOGIN_LOCKED
    ]
    assert len(locks_after) == 1


async def test_locked_user_wrong_password_returns_distinct_lockout(
    app_client, db_session, mock_audit_log
) -> None:
    """A KNOWN, ACTIVE, currently-locked account must surface the distinct
    lockout response EVEN when the submitted password is wrong — that is
    the trap the fix removes (autofilled/stale password masking a lockout
    behind the generic wrong-password message). The lockout path must not
    re-count the failure or extend the lock."""
    from datetime import timedelta

    from app.core.clock import utcnow
    from app.core.models import UserModel

    user_id, email = await seed_user(db_session)

    # Force the account into a locked state directly (failed_login_count
    # at threshold, locked_until in the future).
    user = await db_session.get(UserModel, user_id)
    assert user is not None
    locked_until_before = utcnow() + timedelta(minutes=15)
    user.failed_login_count = 5
    user.locked_until = locked_until_before
    await db_session.flush()

    # Count audit events emitted BEFORE this attempt so we can prove the
    # lockout path adds none.
    audits_before = len(mock_audit_log.write_event.call_args_list)

    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "still-WRONG-1!"},  # wrong pw
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail != "Invalid email or password."
    assert "Too many failed sign-in attempts" in detail

    # Lock NOT extended and counter NOT bumped (no record_failure ran).
    db_session.expire_all()
    user = await db_session.get(UserModel, user_id)
    assert user is not None
    assert user.failed_login_count == 5
    assert user.locked_until == locked_until_before

    # The lockout path emits no audit (no LOGIN_FAILURE, no LOGIN_LOCKED).
    assert len(mock_audit_log.write_event.call_args_list) == audits_before


async def test_login_with_mfa_enrolled_returns_mfa_required(
    app_client, db_session, mock_audit_log
) -> None:
    from datetime import datetime, timezone

    from app.core.models import UserModel

    _user_id, email = await seed_user(db_session)
    # Flip MFA on for this seeded user.
    user = (await db_session.execute(
        __import__("sqlalchemy").select(UserModel).where(UserModel.email == email)
    )).scalar_one()
    user.mfa_secret_encrypted = b"kmsfake:JBSWY3DPEHPK3PXP"
    user.mfa_enrolled_at = datetime.now(timezone.utc)
    await db_session.flush()

    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mfa_required"] is True
    assert body["user_email"] == email
    assert isinstance(body["mfa_challenge_token"], str)
    assert len(body["mfa_challenge_token"]) > 20

    # No LOGIN_SUCCESS yet — login isn't complete.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.LOGIN_SUCCESS not in types


async def test_login_audit_does_not_leak_email_or_password(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    # Inspect every audit call's kwargs — no email, no password ever.
    for call in mock_audit_log.write_event.call_args_list:
        kwargs = dict(call.kwargs)
        for value in kwargs.values():
            text = str(value)
            assert email not in text, f"email leaked into {kwargs}"
            assert "Sup3rSecret" not in text


async def test_admin_role_login_success(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(
        db_session, role=UserRole.ADMIN, password="Adm1nSecret!"
    )
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Adm1nSecret!"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "ADMIN"
