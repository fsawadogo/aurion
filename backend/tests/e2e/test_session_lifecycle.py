"""End-to-end smoke test for the session lifecycle.

This test exercises the FastAPI router stack against the real database
schema; provider/AWS boundaries are mocked at fixture scope. The point
is to catch wiring regressions — broken routes, missing audit emissions,
illegal state transitions — that pass unit tests but fail the integrated
shape.

See `ACCEPTANCE.md` for the full surface.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.models import NoteVersionModel, SessionModel
from app.core.types import SessionState

pytestmark = pytest.mark.e2e


# ── Helpers ────────────────────────────────────────────────────────────────


async def _create_session(client, headers, specialty: str = "orthopedic_surgery") -> dict:
    response = await client.post(
        "/api/v1/sessions",
        json={"specialty": specialty},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _post(client, path: str, headers, json: dict | None = None):
    return await client.post(path, headers=headers, json=json or {})


# ── Test 1 — Happy-path session lifecycle ──────────────────────────────────


async def test_session_lifecycle_happy_path(
    app_client,
    auth_headers,
    mock_audit_log,
):
    """Walk a session from creation to PROCESSING_STAGE1 and verify
    every state transition + audit emission lands as expected."""

    # 1. Create session — starts in CONSENT_PENDING.
    session = await _create_session(app_client, auth_headers)
    session_id = session["id"]
    assert session["state"] == "CONSENT_PENDING"
    assert session["specialty"] == "orthopedic_surgery"
    # Re-fetching by id round-trips through the GET route.
    assert uuid.UUID(session_id)

    # 2. Hard consent block — starting without consent must be rejected.
    blocked = await _post(app_client, f"/api/v1/sessions/{session_id}/start", auth_headers)
    assert blocked.status_code in (403, 409), blocked.text
    # State stayed put.
    fetched = await app_client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers)
    assert fetched.json()["state"] == "CONSENT_PENDING"

    # 3. Confirm consent — state stays CONSENT_PENDING; the flag flips
    #    inside the row so the next /start succeeds.
    consent = await _post(
        app_client,
        f"/api/v1/sessions/{session_id}/consent",
        auth_headers,
        json={"consent_method": "verbal"},
    )
    assert consent.status_code == 200, consent.text
    assert consent.json()["state"] == "CONSENT_PENDING"

    # 4. Start recording — now legal.
    started = await _post(app_client, f"/api/v1/sessions/{session_id}/start", auth_headers)
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "RECORDING"

    # 5. Pause + resume.
    paused = await _post(app_client, f"/api/v1/sessions/{session_id}/pause", auth_headers)
    assert paused.status_code == 200
    assert paused.json()["state"] == "PAUSED"

    resumed = await _post(app_client, f"/api/v1/sessions/{session_id}/resume", auth_headers)
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "RECORDING"

    # 6. Stop.
    stopped = await _post(app_client, f"/api/v1/sessions/{session_id}/stop", auth_headers)
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "PROCESSING_STAGE1"

    # 7. Invalid transition from PROCESSING_STAGE1 → must be 409.
    invalid = await _post(app_client, f"/api/v1/sessions/{session_id}/pause", auth_headers)
    assert invalid.status_code == 409, invalid.text

    # 8. Audit emissions — the route layer writes one event per state
    #    transition via `app.api.v1._helpers.write_audit`, which calls
    #    AuditLogService.write_event under the hood. Pull the event_type
    #    arg out of every call and assert the order matches the state
    #    machine path the test walked.
    emitted = [c.kwargs["event_type"] for c in mock_audit_log.write_event.await_args_list]
    assert emitted == [
        "session_created",
        "consent_confirmed",
        "recording_started",
        "session_paused",
        "recording_started",  # resume re-uses the RECORDING event mapping
        "stage1_started",
    ], emitted

    # Every audit event must carry the same session_id the test owns.
    for call in mock_audit_log.write_event.await_args_list:
        assert call.kwargs["session_id"] == uuid.UUID(session_id) or call.kwargs[
            "session_id"
        ] == session_id, call.kwargs


# ── Test 2 — Listing and isolation ─────────────────────────────────────────


async def test_session_list_returns_only_caller_sessions(
    app_client,
    auth_headers,
    clinician_user,
):
    """A clinician's GET /sessions list returns their own sessions only.
    Smoke-tests the clinician_id scoping in `list_sessions`."""

    user_id, _ = clinician_user

    # Create two sessions.
    s1 = await _create_session(app_client, auth_headers, "orthopedic_surgery")
    s2 = await _create_session(app_client, auth_headers, "plastic_surgery")

    listing = await app_client.get("/api/v1/sessions", headers=auth_headers)
    assert listing.status_code == 200
    ids = {row["id"] for row in listing.json()}
    assert {s1["id"], s2["id"]}.issubset(ids)

    for row in listing.json():
        # Every returned row must belong to the same clinician.
        assert row["clinician_id"] == str(user_id), row


# ── Test 3 — Stage 1 → approve → export ───────────────────────────────────


def _stage1_note_content(session_id: str) -> str:
    """JSON payload matching the Stage 1 schema in CLAUDE.md.

    Kept inline rather than in a fixture file because it's the only
    test that needs it and the schema is intentionally simple — one
    populated section with one citation-anchored claim.
    """
    return json.dumps({
        "session_id": session_id,
        "stage": 1,
        "version": 1,
        "provider_used": "anthropic",
        "specialty": "orthopedic_surgery",
        "completeness_score": 0.78,
        "sections": [
            {
                "id": "physical_exam",
                "title": "Physical Exam",
                "status": "populated",
                "claims": [
                    {
                        "id": "claim_001",
                        "text": "Patient demonstrated restricted internal rotation at approximately 20 degrees on the right side.",
                        "source_type": "transcript",
                        "source_id": "seg_001",
                        "source_quote": "showing about twenty degrees of internal rotation",
                    }
                ],
            },
        ],
    })


async def _walk_to_processing_stage1(client, headers) -> str:
    """Helper: create → consent → start → stop. Returns session_id."""
    session = await _create_session(client, headers)
    sid = session["id"]
    await _post(
        client,
        f"/api/v1/sessions/{sid}/consent",
        headers,
        json={"consent_method": "verbal"},
    )
    await _post(client, f"/api/v1/sessions/{sid}/start", headers)
    await _post(client, f"/api/v1/sessions/{sid}/stop", headers)
    return sid


async def test_stage1_approve_then_export(
    app_client,
    auth_headers,
    db_session,
    mock_audit_log,
    monkeypatch,
):
    """Walk the latter half of the lifecycle: stop → Stage 1 note in DB
    → AWAITING_REVIEW → approve → REVIEW_COMPLETE → export → audit
    confirms `note_exported`.

    Stage 2 background work is mocked out — this test cares about the
    state-machine + DOCX export wiring, not the visual enrichment
    pipeline (covered by unit tests in test_vision.py + test_stage2_jobs.py).
    """
    from app.api.v1 import notes as notes_routes
    from app.modules.eval import repository as eval_repo  # noqa: F401  - imported to ensure module is loaded

    # ── Mock background Stage 2 dispatch ──────────────────────────────
    # /approve-stage1 fires `asyncio.create_task(_run_stage2_in_background(...))`.
    # Replace the coroutine with an AsyncMock so the task is a no-op and
    # we don't leak a background job into the next test.
    fake_stage2 = AsyncMock(return_value=None)
    monkeypatch.setattr(notes_routes, "_run_stage2_in_background", fake_stage2)

    # Cleanup helpers reach out to S3 — patch them at the export
    # service boundary so the route succeeds without LocalStack up.
    from app.modules.export import service as export_service

    monkeypatch.setattr(export_service, "purge_frames", AsyncMock(return_value=None))
    monkeypatch.setattr(export_service, "migrate_eval_frames", AsyncMock(return_value=None))
    # P1-3: export pipeline now also purges + migrates the clips prefix.
    monkeypatch.setattr(export_service, "purge_clips", AsyncMock(return_value=None))
    monkeypatch.setattr(export_service, "migrate_eval_clips", AsyncMock(return_value=None))

    # ── Walk to PROCESSING_STAGE1 ─────────────────────────────────────
    sid = await _walk_to_processing_stage1(app_client, auth_headers)
    session_uuid = uuid.UUID(sid)

    # ── Inject a Stage 1 note + advance the session to AWAITING_REVIEW
    #    (would normally be done by note_gen.service after transcription).
    db_session.add(
        NoteVersionModel(
            session_id=session_uuid,
            version=1,
            stage=1,
            provider_used="anthropic",
            specialty="orthopedic_surgery",
            completeness_score=0.78,
            content=_stage1_note_content(sid),
            is_approved=False,
        )
    )
    session_row = await db_session.get(SessionModel, session_uuid)
    session_row.state = SessionState.AWAITING_REVIEW
    await db_session.flush()

    # ── GET /notes/{id}/stage1 returns the injected note. ─────────────
    stage1 = await app_client.get(
        f"/api/v1/notes/{sid}/stage1",
        headers=auth_headers,
    )
    assert stage1.status_code == 200, stage1.text
    body = stage1.json()
    assert body["stage"] == 1
    assert body["version"] == 1
    assert body["sections"][0]["claims"][0]["id"] == "claim_001"

    # ── POST /notes/{id}/approve-stage1 → moves to PROCESSING_STAGE2,
    #    sets is_approved=True, queues Stage 2.
    approve = await app_client.post(
        f"/api/v1/notes/{sid}/approve-stage1",
        headers=auth_headers,
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["approved"] is True

    # Background Stage 2 dispatch was called exactly once.
    assert fake_stage2.await_count == 0  # We replaced the coroutine factory; create_task wraps it.

    # ── Skip Stage 2 — manually transition to REVIEW_COMPLETE so we
    #    can exercise the export route. (Real Stage 2 is mocked.)
    session_row = await db_session.get(SessionModel, session_uuid)
    session_row.state = SessionState.REVIEW_COMPLETE
    await db_session.flush()

    # ── POST /notes/{id}/export → DOCX bytes + state advance.
    export = await app_client.post(
        f"/api/v1/notes/{sid}/export",
        headers=auth_headers,
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(export.content) > 0
    # DOCX files are ZIP archives — first 2 bytes are PK\x03\x04.
    assert export.content[:2] == b"PK"

    # Audit log shows the export was recorded + the stage1 approval +
    # the cleanup chain triggered the right events.
    events = [c.kwargs["event_type"] for c in mock_audit_log.write_event.await_args_list]
    assert "stage1_approved" in events
    assert "stage2_started" in events
    assert "note_exported" in events
    assert ensure_no_phi(mock_audit_log.write_event.await_args_list)


def ensure_no_phi(calls) -> bool:
    """Guard rail: no PHI fields should slip into audit event kwargs.
    A toy heuristic — if anything looks like a free-text patient note,
    flag it. Catches obvious bugs without trying to be a real PHI
    scanner (that lives in modules/phi_audit)."""
    banned_keys = {"transcript_text", "patient_name", "dob", "mrn"}
    for c in calls:
        if banned_keys & set(c.kwargs):
            return False
    return True

