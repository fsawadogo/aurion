"""E2E regression test for ``delete_my_account`` (Q-02).

Pre-Q-02, the no-sessions branch hardcoded ``deleted_pilot_metrics=0``
in the ``account_deleted`` audit event even when the user had pilot
metrics rows. This test inserts a metrics row for a user with no
sessions, hits ``DELETE /privacy/my-account``, and asserts the audit
event reports the real count.

Lives in ``tests/e2e/`` because it needs the live FastAPI router +
Postgres fixtures from ``conftest.py``. The actual assertion is
narrow — one audit kwarg — but exercising it through the route catches
the latent bug at the same layer the bug existed.
"""

from __future__ import annotations

import pytest

from app.core.models import PilotMetricsModel

pytestmark = pytest.mark.e2e


async def test_delete_account_with_metrics_but_no_sessions_logs_real_count(
    app_client,
    auth_headers,
    clinician_user,
    db_session,
    mock_audit_log,
    monkeypatch,
):
    """User with pilot_metrics rows but no sessions: audit event must
    report ``deleted_pilot_metrics`` matching the real number of rows
    removed.

    Pre-Q-02 behaviour: the no-sessions branch hardcoded zero. Tests
    the fix collapses both branches to one loop with real counters.
    """
    import uuid as _uuid

    from app.api.v1 import privacy as privacy_routes

    user_id, _ = clinician_user

    # S3 purge would normally try to enumerate buckets; mock it out
    # so the test doesn't depend on LocalStack being up.
    monkeypatch.setattr(
        privacy_routes,
        "_purge_s3_objects_for_sessions",
        lambda _sids: 0,
    )

    # Seed two pilot_metrics rows for the user, with no sessions.
    for _ in range(2):
        db_session.add(
            PilotMetricsModel(
                session_id=_uuid.uuid4(),
                clinician_id=user_id,
                specialty="orthopedic_surgery",
            )
        )
    await db_session.flush()

    response = await app_client.delete(
        "/api/v1/privacy/my-account",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    # Exactly one ACCOUNT_DELETED event was emitted (the no-sessions
    # path keyed by "account-{user_id}"), and it carries the REAL
    # metric_count, not zero.
    deleted_calls = [
        c for c in mock_audit_log.write_event.await_args_list
        if c.kwargs.get("event_type") == "account_deleted"
    ]
    assert len(deleted_calls) == 1, deleted_calls
    assert deleted_calls[0].kwargs["deleted_pilot_metrics"] == 2, (
        "Q-02 regression: no-sessions branch must propagate the real "
        "metric_count, not hardcode zero."
    )
    assert deleted_calls[0].kwargs["deleted_sessions"] == 0
    assert deleted_calls[0].kwargs["deleted_note_versions"] == 0
