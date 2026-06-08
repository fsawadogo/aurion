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

import json
import uuid

import pytest
from sqlalchemy import select

from app.core.models import (
    NoteVersionModel,
    PilotMetricsModel,
    SessionModel,
    TranscriptModel,
)

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


async def test_delete_account_erases_transcript_and_child_rows(
    app_client,
    auth_headers,
    clinician_user,
    db_session,
    mock_audit_log,
    monkeypatch,
):
    """#344 — Quebec Law 25 right to erasure must remove the verbatim
    transcript (full PHI text), not just the subset the handler used to
    delete.

    Seeds a real session for the caller with a persisted ``TranscriptModel``
    (+ a note version + pilot metrics), hits ``DELETE
    /privacy/my-account``, then asserts every child row AND the session
    AND the transcript are gone from Postgres.

    Pre-#344 the handler deleted note_versions, pilot_metrics, sessions
    and S3 objects but NOT the ``transcripts`` row — and there is no FK
    cascade (``transcripts.session_id`` is a bare PK) — so the transcript
    PHI was orphaned. This test FAILS against that code: the transcript
    SELECT below still returns a row.
    """
    from app.api.v1 import privacy as privacy_routes

    user_id, _ = clinician_user

    # Don't depend on LocalStack for the S3 purge.
    monkeypatch.setattr(
        privacy_routes,
        "_purge_s3_objects_for_sessions",
        lambda _sids: 0,
    )

    # ── Seed a session owned by the caller via the real create route so
    #    clinician_id is wired exactly like production. ─────────────────
    create = await app_client.post(
        "/api/v1/sessions",
        json={"specialty": "orthopedic_surgery"},
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    session_uuid = uuid.UUID(create.json()["id"])

    # ── Persist the child rows the erasure path must remove. The
    #    transcript holds the full verbatim text = PHI. ────────────────
    db_session.add(
        TranscriptModel(
            session_id=session_uuid,
            provider_used="whisper",
            transcript_json=json.dumps(
                {
                    "session_id": str(session_uuid),
                    "provider_used": "whisper",
                    "segments": [
                        {
                            "id": "seg_001",
                            "start_ms": 0,
                            "end_ms": 3200,
                            "text": "Patient reports right shoulder pain.",
                            "is_visual_trigger": False,
                            "trigger_type": None,
                        }
                    ],
                }
            ),
        )
    )
    db_session.add(
        NoteVersionModel(
            session_id=session_uuid,
            version=1,
            stage=1,
            provider_used="anthropic",
            specialty="orthopedic_surgery",
            completeness_score=0.5,
            content="{}",
            is_approved=False,
        )
    )
    db_session.add(
        PilotMetricsModel(
            session_id=session_uuid,
            clinician_id=user_id,
            specialty="orthopedic_surgery",
        )
    )
    await db_session.flush()

    # Sanity: the transcript really is there before erasure.
    pre = await db_session.execute(
        select(TranscriptModel).where(
            TranscriptModel.session_id == session_uuid
        )
    )
    assert pre.scalars().first() is not None

    # ── Right to erasure. ─────────────────────────────────────────────
    response = await app_client.delete(
        "/api/v1/privacy/my-account",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    # ── Every row keyed to the session must be gone from Postgres. This
    #    is the load-bearing assertion: pre-#344 the transcript row
    #    survived here (orphaned PHI). Checked BEFORE the response/audit
    #    counts so the negative control fails on the actual bug. ────────
    for model in (
        TranscriptModel,
        NoteVersionModel,
        PilotMetricsModel,
        SessionModel,
    ):
        col = (
            model.id  # type: ignore[attr-defined]
            if model is SessionModel
            else model.session_id
        )
        remaining = await db_session.execute(
            select(model).where(col == session_uuid)
        )
        assert remaining.scalars().first() is None, (
            f"#344 regression: {model.__tablename__} row survived account "
            "erasure — orphaned PHI/data left in Postgres."
        )

    # Response payload reports the transcript among the deleted counts.
    body = response.json()
    assert body["deleted"]["transcripts"] == 1, body
    assert body["deleted"]["sessions"] == 1, body

    # ── Audit row reports the transcript count (PHI-free integer). ─────
    deleted_calls = [
        c for c in mock_audit_log.write_event.await_args_list
        if c.kwargs.get("event_type") == "account_deleted"
    ]
    assert len(deleted_calls) == 1, deleted_calls
    assert deleted_calls[0].kwargs["deleted_transcripts"] == 1
    assert deleted_calls[0].kwargs["deleted_note_versions"] == 1
    assert deleted_calls[0].kwargs["deleted_pilot_metrics"] == 1
    assert deleted_calls[0].kwargs["deleted_sessions"] == 1
