# ruff: noqa: F401, F811
"""Integration tests for /admin/users + /admin/users/{id}/reset-password.

AUTH-PIVOT-BACKEND admin user lifecycle.
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


async def _admin_access(app_client, db_session) -> tuple[str, str]:
    _id, email = await seed_user(
        db_session, role=UserRole.ADMIN, password="Adm1nSecret!"
    )
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Adm1nSecret!"},
    )
    return login.json()["access_token"], email


async def test_admin_creates_user_with_temp_password(
    app_client, db_session, mock_audit_log
) -> None:
    access, _admin_email = await _admin_access(app_client, db_session)
    new_email = f"newuser.{__import__('uuid').uuid4().hex[:6]}@test.local"
    response = await app_client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "email": new_email,
            "full_name": "New Clinician",
            "role": "CLINICIAN",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == new_email.lower()
    assert body["role"] == "CLINICIAN"
    assert "temp_password" in body
    temp = body["temp_password"]
    assert len(temp) == 12

    # The temp password works on /login.
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": new_email, "password": temp},
    )
    assert login.status_code == 200, login.text


async def test_create_user_requires_admin(
    app_client, db_session
) -> None:
    _id, clinician_email = await seed_user(db_session)
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": clinician_email, "password": "Sup3rSecret!"},
    )
    clinician_access = login.json()["access_token"]
    response = await app_client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {clinician_access}"},
        json={
            "email": "should-not-work@test.local",
            "full_name": "X",
            "role": "CLINICIAN",
        },
    )
    assert response.status_code == 403


async def test_admin_reset_password_rotates_temp(
    app_client, db_session, mock_audit_log
) -> None:
    admin_access, _admin_email = await _admin_access(app_client, db_session)
    target_id, target_email = await seed_user(db_session)

    response = await app_client.post(
        f"/api/v1/admin/users/{target_id}/reset-password",
        headers={"Authorization": f"Bearer {admin_access}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    new_temp = body["temp_password"]
    assert len(new_temp) == 12

    # New temp works on /login.
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": target_email, "password": new_temp},
    )
    assert login.status_code == 200

    # Old password rejected.
    old_login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": target_email, "password": "Sup3rSecret!"},
    )
    assert old_login.status_code == 401

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.ADMIN_PASSWORD_RESET_ISSUED in types
    # PASSWORD_CHANGED with via=admin_reset.
    pw_changes = [
        c.kwargs
        for c in mock_audit_log.write_event.call_args_list
        if c.kwargs["event_type"] == AuditEventType.PASSWORD_CHANGED
    ]
    admin_resets = [c for c in pw_changes if c.get("via") == "admin_reset"]
    assert len(admin_resets) == 1


async def test_admin_reset_password_requires_admin(
    app_client, db_session
) -> None:
    _id, clinician_email = await seed_user(db_session)
    target_id, _target_email = await seed_user(db_session)
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": clinician_email, "password": "Sup3rSecret!"},
    )
    clinician_access = login.json()["access_token"]
    response = await app_client.post(
        f"/api/v1/admin/users/{target_id}/reset-password",
        headers={"Authorization": f"Bearer {clinician_access}"},
    )
    assert response.status_code == 403
