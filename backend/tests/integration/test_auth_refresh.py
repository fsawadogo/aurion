# ruff: noqa: F401, F811
"""Integration tests for /auth/refresh + /auth/logout (AUTH-PIVOT-BACKEND)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow

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


async def _login_get_refresh(app_client, email: str) -> tuple[str, str]:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["access_token"], body["refresh_token"]


async def test_refresh_rotates_token(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    _access1, refresh1 = await _login_get_refresh(app_client, email)

    response = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh1}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    new_refresh = body["refresh_token"]
    assert new_refresh != refresh1, "refresh token must rotate"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20
    assert body["expires_in"] == 1800

    # Replay of the old refresh now fails.
    replay = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh1}
    )
    assert replay.status_code == 401

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.REFRESH_TOKEN_ROTATED in types


async def test_refresh_with_unknown_token_returns_401(
    app_client, db_session, mock_audit_log
) -> None:
    response = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "definitely-not-real"}
    )
    assert response.status_code == 401


async def test_refresh_with_expired_token_returns_401(
    app_client, db_session
) -> None:
    """Hand-edit the persisted refresh row to make it expired."""
    from sqlalchemy import select

    from app.core.models import RefreshTokenModel

    _user_id, email = await seed_user(db_session)
    _access, refresh = await _login_get_refresh(app_client, email)

    row = (
        await db_session.execute(select(RefreshTokenModel))
    ).scalar_one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    await db_session.flush()

    response = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    assert response.status_code == 401


async def test_logout_revokes_refresh(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    _access, refresh = await _login_get_refresh(app_client, email)

    response = await app_client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh}
    )
    assert response.status_code == 204

    # Subsequent refresh fails.
    response = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    assert response.status_code == 401

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.LOGOUT in types
    assert AuditEventType.REFRESH_TOKEN_REVOKED in types


async def test_logout_with_unknown_token_returns_204(app_client) -> None:
    """Defense against attacker probes — logout never reveals whether
    the token existed."""
    response = await app_client.post(
        "/api/v1/auth/logout", json={"refresh_token": "not-a-real-token"}
    )
    assert response.status_code == 204


async def test_refresh_response_never_logs_raw_token(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    _access, refresh = await _login_get_refresh(app_client, email)
    response = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    new_refresh = response.json()["refresh_token"]
    for call in mock_audit_log.write_event.call_args_list:
        for v in call.kwargs.values():
            text = str(v)
            assert refresh not in text, "old refresh token leaked to audit"
            assert new_refresh not in text, "new refresh token leaked to audit"
