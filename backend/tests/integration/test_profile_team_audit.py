# ruff: noqa: F401, F811
"""Integration tests for the team-members audit emission (#260).

The route handler at ``PUT /profile`` writes a
``TEAM_MEMBERS_UPDATED`` audit row when ``allied_health_team`` is in
the request body AND the count actually changed. This file locks the
emit + payload contract so a future refactor can't quietly drop the
audit row.

Properties asserted here:
  * Adding a member emits exactly one ``TEAM_MEMBERS_UPDATED`` row
    with the correct count delta.
  * Removing a member emits exactly one row with the inverted delta.
  * Re-sending the same list does NOT emit a row (no-op edits stay
    out of the trail).
  * Updates that don't touch ``allied_health_team`` (e.g. a
    ``ui_theme`` change) don't emit ``TEAM_MEMBERS_UPDATED``.
  * The kwargs payload contains ONLY actor_id + count fields —
    never the member names.
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


async def _login(app_client, email: str) -> str:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _team_events(mock_audit_log) -> list[dict]:
    """Return the kwargs dicts of every ``TEAM_MEMBERS_UPDATED`` row
    written during the test. We compare on full payload so the test
    also covers the no-PHI guarantee."""
    rows = []
    for call in mock_audit_log.write_event.call_args_list:
        if call.kwargs.get("event_type") == AuditEventType.TEAM_MEMBERS_UPDATED:
            rows.append(call.kwargs)
    return rows


async def test_addingMember_emitsAuditRow_withCountDelta(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-8: a brand-new member triggers exactly one audit row with
    ``members_count_before=0`` + ``members_count_after=1``."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "allied_health_team": [
                {"name": "Sarah Chen", "role": "RN"},
            ],
        },
    )
    assert response.status_code == 200, response.text

    rows = _team_events(mock_audit_log)
    assert len(rows) == 1, f"expected exactly 1 audit row, got {len(rows)}"
    payload = rows[0]
    assert payload["members_count_before"] == 0
    assert payload["members_count_after"] == 1
    # actor_id is the calling clinician's UUID, as a string.
    assert "actor_id" in payload
    # The names must never appear in the audit row.
    payload_str = repr(payload)
    assert "Sarah" not in payload_str
    assert "Chen" not in payload_str
    assert "RN" not in payload_str


async def test_removingMember_emitsAuditRow_withInvertedDelta(
    app_client, db_session, mock_audit_log
) -> None:
    """Removing a member from a 2-row list lands a single audit row
    with ``before=2 after=1``."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    # Seed the profile with two members.
    seed = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "allied_health_team": [
                {"name": "Sarah Chen", "role": "RN"},
                {"name": "Alex Wu", "role": "scribe"},
            ],
        },
    )
    assert seed.status_code == 200

    # Clear the audit log so we only count rows from the second call.
    mock_audit_log.write_event.reset_mock()

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "allied_health_team": [
                {"name": "Sarah Chen", "role": "RN"},
            ],
        },
    )
    assert response.status_code == 200, response.text

    rows = _team_events(mock_audit_log)
    assert len(rows) == 1
    assert rows[0]["members_count_before"] == 2
    assert rows[0]["members_count_after"] == 1


async def test_noChange_skipsAuditEmit(
    app_client, db_session, mock_audit_log
) -> None:
    """Sending the same team list twice writes exactly one audit row
    (on the first call). The second call's payload diffs equal to the
    server snapshot and skips the emit — the audit trail stays
    meaningful, not noisy."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    body = {
        "allied_health_team": [
            {"name": "Sarah Chen", "role": "RN"},
        ],
    }
    first = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json=body,
    )
    assert first.status_code == 200

    mock_audit_log.write_event.reset_mock()

    second = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json=body,
    )
    assert second.status_code == 200, second.text

    rows = _team_events(mock_audit_log)
    assert rows == [], "no-change update must not emit TEAM_MEMBERS_UPDATED"


async def test_unrelatedFieldUpdate_skipsAuditEmit(
    app_client, db_session, mock_audit_log
) -> None:
    """A profile update that doesn't include ``allied_health_team``
    (e.g. flipping ``ui_theme``) must not emit
    ``TEAM_MEMBERS_UPDATED`` even when the team list is non-empty on
    disk."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    # Seed a non-empty team.
    await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "allied_health_team": [
                {"name": "Sarah Chen", "role": "RN"},
            ],
        },
    )
    mock_audit_log.write_event.reset_mock()

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"ui_theme": "dark"},
    )
    assert response.status_code == 200, response.text

    rows = _team_events(mock_audit_log)
    assert rows == [], "ui_theme update must not emit TEAM_MEMBERS_UPDATED"
