# ruff: noqa: F401, F811
"""Integration tests for /me/mfa/* (#163).

Status / enroll / verify-enroll / disable, end-to-end against real
Postgres + the shared `_auth_fixtures` harness.
"""

from __future__ import annotations

import pyotp
import pytest

from app.core.audit_events import AuditEventType

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


async def _login_and_get_access(app_client, email: str) -> str:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_status_unenrolled(app_client, db_session) -> None:
    """AC-1: GET /me/mfa/status returns enrolled=False on a fresh user."""
    _user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)

    response = await app_client.get(
        "/api/v1/me/mfa/status",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"enrolled": False, "last_verified_at": None}


async def test_enroll_does_not_persist(app_client, db_session) -> None:
    """AC-2: /me/mfa/enroll returns the bundle without mutating the user row."""
    from sqlalchemy import select

    from app.core.models import UserModel

    user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)

    response = await app_client.post(
        "/api/v1/me/mfa/enroll",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["qr_uri"].startswith("otpauth://totp/")
    assert len(body["secret"]) == 32
    assert len(body["recovery_codes"]) == 8
    # Recovery codes look like XXXX-XXXX with the unambiguous alphabet.
    for code in body["recovery_codes"]:
        assert len(code) == 9 and code[4] == "-"
    assert isinstance(body["setup_token"], str) and len(body["setup_token"]) > 50

    # Nothing persisted.
    db_session.expire_all()
    user = (
        await db_session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
    ).scalar_one()
    assert user.mfa_enrolled_at is None
    assert user.mfa_secret_encrypted is None
    assert user.mfa_recovery_codes_hashed is None


async def test_verify_enroll_persists(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-3: /me/mfa/verify-enroll with a valid code persists secret+codes."""
    from sqlalchemy import select

    from app.core.models import UserModel

    user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)

    enroll = await app_client.post(
        "/api/v1/me/mfa/enroll",
        headers={"Authorization": f"Bearer {access}"},
    )
    body = enroll.json()
    code = pyotp.TOTP(body["secret"]).now()

    verify = await app_client.post(
        "/api/v1/me/mfa/verify-enroll",
        headers={"Authorization": f"Bearer {access}"},
        json={"setup_token": body["setup_token"], "code": code},
    )
    assert verify.status_code == 204, verify.text

    db_session.expire_all()
    user = (
        await db_session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
    ).scalar_one()
    assert user.mfa_enrolled_at is not None
    assert user.mfa_secret_encrypted is not None
    assert isinstance(user.mfa_recovery_codes_hashed, list)
    assert len(user.mfa_recovery_codes_hashed) == 8

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.MFA_ENROLLED in types


async def test_verify_enroll_rejects_bad_code(
    app_client, db_session
) -> None:
    """A wrong TOTP code at verify-enroll fails with 400 and does not persist."""
    from sqlalchemy import select

    from app.core.models import UserModel

    user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)
    enroll = await app_client.post(
        "/api/v1/me/mfa/enroll",
        headers={"Authorization": f"Bearer {access}"},
    )
    setup_token = enroll.json()["setup_token"]

    bad = await app_client.post(
        "/api/v1/me/mfa/verify-enroll",
        headers={"Authorization": f"Bearer {access}"},
        json={"setup_token": setup_token, "code": "000000"},
    )
    assert bad.status_code == 400, bad.text

    db_session.expire_all()
    user = (
        await db_session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
    ).scalar_one()
    assert user.mfa_enrolled_at is None


async def test_verify_enroll_rejects_other_users_setup_token(
    app_client, db_session
) -> None:
    """A user can't reuse another user's setup_token to enroll themselves."""
    _alice_id, alice_email = await seed_user(db_session)
    _bob_id, bob_email = await seed_user(db_session)

    alice_access = await _login_and_get_access(app_client, alice_email)
    alice_enroll = await app_client.post(
        "/api/v1/me/mfa/enroll",
        headers={"Authorization": f"Bearer {alice_access}"},
    )
    alice_body = alice_enroll.json()

    bob_access = await _login_and_get_access(app_client, bob_email)
    code = pyotp.TOTP(alice_body["secret"]).now()
    bob_response = await app_client.post(
        "/api/v1/me/mfa/verify-enroll",
        headers={"Authorization": f"Bearer {bob_access}"},
        json={"setup_token": alice_body["setup_token"], "code": code},
    )
    # Even with a valid code, the setup_token is bound to Alice's
    # user_id — Bob's enroll attempt must 400.
    assert bob_response.status_code == 400, bob_response.text


async def test_disable_requires_code(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-4: DELETE /me/mfa needs a fresh code and clears the secret."""
    from sqlalchemy import select

    from app.core.models import UserModel

    user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)
    enroll = await app_client.post(
        "/api/v1/me/mfa/enroll",
        headers={"Authorization": f"Bearer {access}"},
    )
    body = enroll.json()
    await app_client.post(
        "/api/v1/me/mfa/verify-enroll",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "setup_token": body["setup_token"],
            "code": pyotp.TOTP(body["secret"]).now(),
        },
    )

    # Bad code → 400.
    bad = await app_client.request(
        "DELETE",
        "/api/v1/me/mfa",
        headers={"Authorization": f"Bearer {access}"},
        json={"current_code": "000000"},
    )
    assert bad.status_code == 400, bad.text

    # Good code → 204 + columns wiped.
    good = await app_client.request(
        "DELETE",
        "/api/v1/me/mfa",
        headers={"Authorization": f"Bearer {access}"},
        json={"current_code": pyotp.TOTP(body["secret"]).now()},
    )
    assert good.status_code == 204, good.text

    db_session.expire_all()
    user = (
        await db_session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
    ).scalar_one()
    assert user.mfa_enrolled_at is None
    assert user.mfa_secret_encrypted is None
    assert user.mfa_recovery_codes_hashed is None

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.MFA_DISABLED in types
