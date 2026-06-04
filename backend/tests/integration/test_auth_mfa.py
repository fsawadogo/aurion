# ruff: noqa: F401, F811
"""Integration tests for MFA endpoints (AUTH-PIVOT-BACKEND).

Setup → verify → enrolled → login requires code → admin clear.
"""

from __future__ import annotations

import pyotp
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


async def _login_and_get_access(app_client, email: str) -> str:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_mfa_setup_returns_secret_and_provisioning_uri(
    app_client, db_session
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)

    response = await app_client.get(
        "/api/v1/auth/mfa/setup",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["secret"], str)
    assert len(body["secret"]) == 32
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert "issuer=Aurion" in body["provisioning_uri"]


async def test_mfa_setup_verify_completes_enrollment(
    app_client, db_session, mock_audit_log
) -> None:
    from sqlalchemy import select

    from app.core.models import UserModel

    _user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)

    setup_resp = await app_client.get(
        "/api/v1/auth/mfa/setup",
        headers={"Authorization": f"Bearer {access}"},
    )
    secret = setup_resp.json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify_resp = await app_client.post(
        "/api/v1/auth/mfa/setup/verify",
        headers={"Authorization": f"Bearer {access}"},
        json={"code": code},
    )
    assert verify_resp.status_code == 204

    # mfa_enrolled_at populated.
    db_session.expire_all()
    user = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == email)
        )
    ).scalar_one()
    assert user.mfa_enrolled_at is not None

    # MFA_ENROLLED audit emitted.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.MFA_ENROLLED in types


async def test_mfa_setup_verify_rejects_bad_code(
    app_client, db_session
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)
    await app_client.get(
        "/api/v1/auth/mfa/setup",
        headers={"Authorization": f"Bearer {access}"},
    )

    response = await app_client.post(
        "/api/v1/auth/mfa/setup/verify",
        headers={"Authorization": f"Bearer {access}"},
        json={"code": "000000"},
    )
    assert response.status_code == 400


async def test_login_with_mfa_enrolled_requires_code(
    app_client, db_session
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login_and_get_access(app_client, email)
    setup_resp = await app_client.get(
        "/api/v1/auth/mfa/setup",
        headers={"Authorization": f"Bearer {access}"},
    )
    secret = setup_resp.json()["secret"]
    await app_client.post(
        "/api/v1/auth/mfa/setup/verify",
        headers={"Authorization": f"Bearer {access}"},
        json={"code": pyotp.TOTP(secret).now()},
    )

    # Login must now return mfa_required.
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert login.status_code == 200
    body = login.json()
    assert body.get("mfa_required") is True
    challenge = body["mfa_challenge_token"]

    # Bad code → 401.
    bad = await app_client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"mfa_challenge_token": challenge, "code": "000000"},
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Invalid email or password."

    # Good code → tokens.
    good = await app_client.post(
        "/api/v1/auth/mfa/verify-login",
        json={
            "mfa_challenge_token": challenge,
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert good.status_code == 200, good.text
    body = good.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["mfa_enrolled"] is True


async def test_admin_clear_mfa_requires_admin(
    app_client, db_session, mock_audit_log
) -> None:
    """DELETE /auth/mfa: 403 for CLINICIAN, 204 for ADMIN."""
    _clinician_id, clinician_email = await seed_user(db_session)
    admin_id, admin_email = await seed_user(
        db_session, role=UserRole.ADMIN, password="Adm1nSecret!"
    )
    target_id, target_email = await seed_user(db_session)

    # Clinician access → 403.
    clinician_access = await _login_and_get_access(app_client, clinician_email)
    response = await app_client.request(
        "DELETE",
        "/api/v1/auth/mfa",
        headers={"Authorization": f"Bearer {clinician_access}"},
        json={"user_id": str(target_id)},
    )
    assert response.status_code == 403

    # Admin access → 204.
    admin_login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": "Adm1nSecret!"},
    )
    admin_access = admin_login.json()["access_token"]
    response = await app_client.request(
        "DELETE",
        "/api/v1/auth/mfa",
        headers={"Authorization": f"Bearer {admin_access}"},
        json={"user_id": str(target_id)},
    )
    assert response.status_code == 204

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.MFA_RESET in types
