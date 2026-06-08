# ruff: noqa: F401, F811
"""Integration tests for /auth/forgot-password + /auth/reset-password.

AUTH-PIVOT-BACKEND.
"""

from __future__ import annotations

import logging

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


def _extract_reset_link(caplog) -> str:
    """The dev-mode email module logs the reset link at INFO."""
    for record in caplog.records:
        if "password reset link for" in record.getMessage():
            return record.getMessage().split(": ", 1)[1]
    raise AssertionError("reset link not found in caplog")


async def test_forgot_password_for_existing_user_issues_token_and_logs_link(
    app_client, db_session, mock_audit_log, caplog
) -> None:
    user_id, email = await seed_user(db_session)
    caplog.set_level(logging.INFO, logger="aurion.auth.email")

    response = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )
    assert response.status_code == 204

    # Dev mode: link is logged.
    link = _extract_reset_link(caplog)
    assert "token=" in link

    # Audit event.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.PASSWORD_RESET_REQUESTED in types

    # The token is in the DB.
    from sqlalchemy import select

    from app.core.models import PasswordResetTokenModel

    rows = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(
                PasswordResetTokenModel.user_id == user_id
            )
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_forgot_password_returns_204_when_email_send_raises(
    app_client, db_session, mock_audit_log, monkeypatch, caplog
) -> None:
    """SES delivery failure (e.g. sandbox blocking an unverified
    recipient) must NOT surface as a 500 — that would both break the
    "always 204" contract and leak account existence (a real-but-
    undeliverable address would 500 while an unknown one 204s). The
    token is already persisted, so the endpoint stays 204 and still
    writes the audit row. See issue #349."""
    from botocore.exceptions import ClientError

    import app.api.v1.auth as auth_module

    caplog.set_level(logging.ERROR, logger="aurion.auth")
    user_id, email = await seed_user(db_session)

    async def _boom(*, user, raw_token):  # noqa: ANN001, ANN202
        raise ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "redacted"}},
            "SendEmail",
        )

    monkeypatch.setattr(auth_module, "send_password_reset_email", _boom)

    response = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )
    assert response.status_code == 204

    # The failure log carries only the exception class — never the
    # email, link, or token.
    failure_logs = [
        r.getMessage()
        for r in caplog.records
        if "password reset email send failed" in r.getMessage()
    ]
    assert failure_logs, "expected the send-failure to be logged"
    for msg in failure_logs:
        assert email not in msg
        assert "token=" not in msg
        assert "ClientError" in msg

    # The reset token is still issued despite the email failure.
    from sqlalchemy import select

    from app.core.models import PasswordResetTokenModel

    rows = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(
                PasswordResetTokenModel.user_id == user_id
            )
        )
    ).scalars().all()
    assert len(rows) == 1

    # The audit row is still written.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.PASSWORD_RESET_REQUESTED in types


async def test_forgot_password_for_unknown_email_returns_204_no_audit(
    app_client, db_session, mock_audit_log, caplog
) -> None:
    caplog.set_level(logging.INFO, logger="aurion.auth.email")
    response = await app_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody.never@nowhere.test"},
    )
    assert response.status_code == 204
    # No reset link logged.
    assert all(
        "password reset link" not in r.getMessage() for r in caplog.records
    )
    # No PASSWORD_RESET_REQUESTED audit.
    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.PASSWORD_RESET_REQUESTED not in types


async def test_reset_password_with_valid_token_sets_password(
    app_client, db_session, mock_audit_log, caplog
) -> None:
    _user_id, email = await seed_user(db_session)
    caplog.set_level(logging.INFO, logger="aurion.auth.email")
    await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )
    link = _extract_reset_link(caplog)
    raw_token = link.split("token=", 1)[1]

    response = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "BrandNewSecret1!"},
    )
    assert response.status_code == 204

    # New password works on /login.
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "BrandNewSecret1!"},
    )
    assert login.status_code == 200

    # Old password rejected.
    old_login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert old_login.status_code == 401

    # PASSWORD_CHANGED audit emitted.
    changes = [
        c.kwargs
        for c in mock_audit_log.write_event.call_args_list
        if c.kwargs["event_type"] == AuditEventType.PASSWORD_CHANGED
    ]
    assert len(changes) == 1
    assert changes[0]["via"] == "self_reset"


async def test_reset_password_consumes_token_single_use(
    app_client, db_session, caplog
) -> None:
    _user_id, email = await seed_user(db_session)
    caplog.set_level(logging.INFO, logger="aurion.auth.email")
    await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )
    raw_token = _extract_reset_link(caplog).split("token=", 1)[1]

    first = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "BrandNewSecret1!"},
    )
    assert first.status_code == 204

    second = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "AnotherSecret9!"},
    )
    assert second.status_code == 400


async def test_reset_password_with_expired_token_returns_400(
    app_client, db_session, caplog
) -> None:
    from datetime import timedelta

    from sqlalchemy import select

    from app.core.clock import utcnow
    from app.core.models import PasswordResetTokenModel

    _user_id, email = await seed_user(db_session)
    caplog.set_level(logging.INFO, logger="aurion.auth.email")
    await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )
    raw_token = _extract_reset_link(caplog).split("token=", 1)[1]

    # Push the row's expires_at into the past.
    row = (
        await db_session.execute(select(PasswordResetTokenModel))
    ).scalar_one()
    row.expires_at = utcnow() - timedelta(hours=1)
    await db_session.flush()

    response = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "ShouldNotWork9!"},
    )
    assert response.status_code == 400


async def test_password_reset_revokes_refresh_tokens(
    app_client, db_session, caplog
) -> None:
    """A successful password reset must invalidate every existing
    refresh token for the user — see plan AC-10."""
    from sqlalchemy import select

    from app.core.models import RefreshTokenModel

    _user_id, email = await seed_user(db_session)
    # Log in to issue a refresh token.
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    refresh_token = login.json()["refresh_token"]

    # Request a reset link + consume it.
    caplog.set_level(logging.INFO, logger="aurion.auth.email")
    await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )
    raw_token = _extract_reset_link(caplog).split("token=", 1)[1]
    await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "BrandNewSecret1!"},
    )

    # The pre-existing refresh is now revoked.
    rows = (
        await db_session.execute(select(RefreshTokenModel))
    ).scalars().all()
    assert all(row.revoked_at is not None for row in rows)

    response = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert response.status_code == 401
