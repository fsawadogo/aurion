# ruff: noqa: F401, F811
"""Integration tests for /me/sessions/* (#163).

Listing / revoke-one / revoke-all, with the row-level ownership
contract enforced.
"""

from __future__ import annotations

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


async def _login(app_client, email: str) -> dict:
    """Run /login and return the full token bundle."""
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_only_returns_own(app_client, db_session) -> None:
    """AC-5: /me/sessions returns only the caller's own active refresh rows."""
    _alice_id, alice_email = await seed_user(db_session)
    _bob_id, bob_email = await seed_user(db_session)

    # Alice has two sessions (re-login produces a second refresh row),
    # Bob has one.
    alice_a = await _login(app_client, alice_email)
    alice_b = await _login(app_client, alice_email)
    _bob = await _login(app_client, bob_email)

    list_resp = await app_client.get(
        "/api/v1/me/sessions",
        headers={"Authorization": f"Bearer {alice_a['access_token']}"},
    )
    assert list_resp.status_code == 200, list_resp.text
    rows = list_resp.json()
    # Alice sees two of her own rows.
    assert len(rows) == 2
    # Exactly one row is_current — the one made by alice_a.
    current_count = sum(1 for r in rows if r["is_current"])
    assert current_count == 1
    # Each row carries the new metadata fields.
    for r in rows:
        assert "device_hint" in r
        assert "ip_class" in r
        assert "created_at" in r
        assert "last_used_at" in r


async def test_revoke_own_and_other(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-6: revoke a row I own succeeds; a row I don't own returns 404."""
    _alice_id, alice_email = await seed_user(db_session)
    _bob_id, bob_email = await seed_user(db_session)

    alice = await _login(app_client, alice_email)
    bob = await _login(app_client, bob_email)

    # Alice lists her sessions to find a row id she owns.
    alice_rows = (
        await app_client.get(
            "/api/v1/me/sessions",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
    ).json()
    alice_session_id = alice_rows[0]["id"]

    # Bob tries to revoke Alice's row → 404.
    bob_revoke = await app_client.post(
        f"/api/v1/me/sessions/{alice_session_id}/revoke",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
    )
    assert bob_revoke.status_code == 404, bob_revoke.text

    # Alice revokes a row she owns — to keep the test deterministic,
    # she opens a second session and revokes the FIRST one.
    alice_second = await _login(app_client, alice_email)
    alice_rows = (
        await app_client.get(
            "/api/v1/me/sessions",
            headers={"Authorization": f"Bearer {alice_second['access_token']}"},
        )
    ).json()
    # Pick the row that is NOT current — that's the original alice
    # session.
    target = [r for r in alice_rows if not r["is_current"]][0]
    revoke = await app_client.post(
        f"/api/v1/me/sessions/{target['id']}/revoke",
        headers={"Authorization": f"Bearer {alice_second['access_token']}"},
    )
    assert revoke.status_code == 204, revoke.text

    # After revoke, the row is gone from the list.
    alice_rows_after = (
        await app_client.get(
            "/api/v1/me/sessions",
            headers={"Authorization": f"Bearer {alice_second['access_token']}"},
        )
    ).json()
    ids_after = {r["id"] for r in alice_rows_after}
    assert target["id"] not in ids_after

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.SESSION_REVOKED in types


async def test_revoke_all_keeps_current(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-7: revoke-all kills every active row except the calling one."""
    _alice_id, alice_email = await seed_user(db_session)

    # Three Alice logins → three active refresh rows.
    await _login(app_client, alice_email)
    await _login(app_client, alice_email)
    alice_current = await _login(app_client, alice_email)

    revoke = await app_client.post(
        "/api/v1/me/sessions/revoke-all",
        headers={"Authorization": f"Bearer {alice_current['access_token']}"},
    )
    assert revoke.status_code == 204, revoke.text

    rows_after = (
        await app_client.get(
            "/api/v1/me/sessions",
            headers={"Authorization": f"Bearer {alice_current['access_token']}"},
        )
    ).json()
    # Exactly one row remains — the current one.
    assert len(rows_after) == 1
    assert rows_after[0]["is_current"] is True

    types = [
        c.kwargs["event_type"]
        for c in mock_audit_log.write_event.call_args_list
    ]
    assert AuditEventType.SESSIONS_REVOKED_ALL in types
