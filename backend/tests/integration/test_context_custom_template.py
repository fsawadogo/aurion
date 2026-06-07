# ruff: noqa: F401, F811
"""Integration tests for binding a CUSTOM template to a context on
PUT /profile (#318, B3).

End-to-end route glue the unit tests can't reach:
  * An OWNED custom ``template_ref`` is accepted and round-trips (the ref
    is preserved, no longer forced null).
  * A NON-OWNED ref is REJECTED at PUT (SECURITY) — 422, reason-only, the
    ref never echoes, no audit row.
  * A nonexistent (well-formed UUID, no row) ref → 422.
  * ``template_key`` + ``template_ref`` together → 422 (mutual exclusion).
  * The ``PROFILE_CONTEXTS_UPDATED`` audit row carries the count-only
    ``custom_templates_attached`` delta — never the ref / id.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.audit_events import AuditEventType
from app.modules.custom_templates import service as custom_templates_service

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


def _template_payload(key: str) -> dict:
    return {
        "key": key,
        "display_name": "Custom Lower Limb",
        "version": "1.0",
        "sections": [
            {"id": "chief_complaint", "title": "Chief Complaint", "required": True},
            {"id": "plan", "title": "Plan", "required": True},
        ],
    }


async def _make_custom_template(
    db_session, owner_id: uuid.UUID, key: str
) -> uuid.UUID:
    row = await custom_templates_service.create_for_owner(
        owner_id, _template_payload(key), db_session
    )
    await db_session.flush()
    return row.id


def _context_events(mock_audit_log) -> list[dict]:
    return [
        call.kwargs
        for call in mock_audit_log.write_event.call_args_list
        if call.kwargs.get("event_type")
        == AuditEventType.PROFILE_CONTEXTS_UPDATED
    ]


# ── Owned ref accepted + round-trips ─────────────────────────────────────────


async def test_putAcceptsOwnedCustomRef(
    app_client, db_session, mock_audit_log
) -> None:
    user_id, email = await seed_user(db_session)
    ref = str(await _make_custom_template(db_session, user_id, "ll_custom"))
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [{"label": "LL", "template_ref": ref}]
            }
        },
    )
    assert response.status_code == 200, response.text
    row = response.json()["contexts_per_visit_type"]["new_patient"][0]
    # The ref is PRESERVED now (B3), not forced null; template_key stays null.
    assert row["template_ref"] == ref
    assert row["template_key"] is None


# ── Non-owned / nonexistent ref rejected at PUT (SECURITY) ───────────────────


async def test_putRejectsNonOwnedCustomRef(
    app_client, db_session, mock_audit_log
) -> None:
    """SECURITY: a ref to a custom template owned by ANOTHER clinician is
    rejected at write — never silently dropped, never accepted. The 422
    body never echoes the ref."""
    user_id, email = await seed_user(db_session)
    other_owner = uuid.uuid4()
    foreign_ref = str(
        await _make_custom_template(db_session, other_owner, "foreign_custom")
    )
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [{"label": "LL", "template_ref": foreign_ref}]
            }
        },
    )
    assert response.status_code == 422, response.text
    assert foreign_ref not in response.text
    assert _context_events(mock_audit_log) == []


async def test_putRejectsNonexistentCustomRef(
    app_client, db_session, mock_audit_log
) -> None:
    user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)
    missing_ref = str(uuid.uuid4())

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [{"label": "LL", "template_ref": missing_ref}]
            }
        },
    )
    assert response.status_code == 422, response.text
    assert _context_events(mock_audit_log) == []


# ── Mutual exclusion ─────────────────────────────────────────────────────────


async def test_putRejectsBothTemplateKeyAndRef(
    app_client, db_session, mock_audit_log
) -> None:
    user_id, email = await seed_user(db_session)
    ref = str(await _make_custom_template(db_session, user_id, "both_custom"))
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [
                    {
                        "label": "LL",
                        "template_key": "orthopedic_surgery",
                        "template_ref": ref,
                    }
                ]
            }
        },
    )
    assert response.status_code == 422, response.text
    assert _context_events(mock_audit_log) == []


# ── Audit: count-only custom-template attach ─────────────────────────────────


async def test_emitsCustomTemplateAttachedCountOnly(
    app_client, db_session, mock_audit_log
) -> None:
    user_id, email = await seed_user(db_session)
    ref = str(await _make_custom_template(db_session, user_id, "audit_custom"))
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [{"label": "SecretLL", "template_ref": ref}]
            }
        },
    )
    assert response.status_code == 200, response.text

    rows = _context_events(mock_audit_log)
    assert len(rows) == 1
    payload = rows[0]
    assert payload["custom_templates_attached"] == 1
    assert payload["custom_templates_detached"] == 0
    assert payload["templates_attached"] == 0
    assert "actor_id" in payload
    # Count-only: the ref UUID, the label, and any context id never ride
    # along in the audit row.
    blob = repr(payload)
    assert ref not in blob
    assert "SecretLL" not in blob
    assert "ctx_" not in blob
