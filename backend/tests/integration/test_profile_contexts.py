# ruff: noqa: F401, F811
"""Integration tests for the visit-type → context map on PUT /profile (#313, B1).

End-to-end coverage of the route glue the unit tests can't reach:
  * Contexts persist round-trip; GET returns the full
    ``{id, label, template_key, template_ref}`` shape with explicit nulls.
  * Ids are server-assigned and preserved on a subsequent edit.
  * Orphan visit-type keys (not in the request's consultation_types and
    not a built-in default) are pruned at the route.
  * ``template_key`` membership gate: built-in accepted, unknown → 422.
  * ``template_ref`` ownership/existence is validated at PUT time (#318 /
    B3); a malformed / non-owned ref → 422. Full B3 PUT-time + Stage-1
    coverage lives in ``test_context_custom_template.py``.
  * 30-contexts-per-visit-type cap → 422 before any audit emit.
  * ``PROFILE_CONTEXTS_UPDATED`` fires once on a real diff with AGGREGATE
    COUNTS ONLY — never labels / keys / ids / template names. Same-map and
    unrelated-field updates emit zero rows.
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

_BUILTIN_TEMPLATE = "orthopedic_surgery"


async def _login(app_client, email: str) -> str:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _context_events(mock_audit_log) -> list[dict]:
    rows = []
    for call in mock_audit_log.write_event.call_args_list:
        if (
            call.kwargs.get("event_type")
            == AuditEventType.PROFILE_CONTEXTS_UPDATED
        ):
            rows.append(call.kwargs)
    return rows


# ── Happy paths ───────────────────────────────────────────────────────────


async def test_persistsContextsRoundTrip(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [
                    {"label": "LL", "template_key": _BUILTIN_TEMPLATE},
                    {"label": "Breast"},
                ]
            }
        },
    )
    assert response.status_code == 200, response.text
    ctx_map = response.json()["contexts_per_visit_type"]
    rows = ctx_map["new_patient"]
    assert len(rows) == 2
    # Full shape with explicit nulls survives serialization.
    assert rows[0]["label"] == "LL"
    assert rows[0]["template_key"] == _BUILTIN_TEMPLATE
    assert rows[0]["template_ref"] is None
    assert rows[1]["template_key"] is None
    assert all(r["id"].startswith("ctx_") for r in rows)

    # GET returns the same persisted map.
    got = await app_client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert got.json()["contexts_per_visit_type"] == ctx_map


async def test_serverAssignsAndPreservesIds(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    first = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"contexts_per_visit_type": {"new_patient": [{"label": "LL"}]}},
    )
    minted = first.json()["contexts_per_visit_type"]["new_patient"][0]["id"]
    assert minted.startswith("ctx_")

    second = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [
                    {"id": minted, "label": "LL (lower limb)"},
                    {"label": "Breast"},
                ]
            }
        },
    )
    rows = second.json()["contexts_per_visit_type"]["new_patient"]
    assert rows[0]["id"] == minted
    assert rows[0]["label"] == "LL (lower limb)"
    assert rows[1]["id"] != minted


async def test_prunesOrphanVisitTypeKeys(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": ["new_patient", "Breast"],
            "contexts_per_visit_type": {
                "new_patient": [{"label": "LL"}],
                "Breast": [{"label": "Left"}],
                "Removed": [{"label": "stale"}],  # orphan → pruned
            },
        },
    )
    assert response.status_code == 200, response.text
    keys = set(response.json()["contexts_per_visit_type"])
    assert keys == {"new_patient", "Breast"}


# ── Gates ───────────────────────────────────────────────────────────────


async def test_rejectsUnknownTemplateKey(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [
                    {"label": "LL", "template_key": "not_a_real_template"}
                ]
            }
        },
    )
    assert response.status_code == 422
    assert _context_events(mock_audit_log) == []


async def test_malformedTemplateRefRejected(
    app_client, db_session, mock_audit_log
) -> None:
    """#318 / B3: ``template_ref`` is no longer forced null — a malformed
    (non-UUID) ref is REJECTED at PUT, not silently dropped. The 422
    body never echoes the rejected ref."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [{"label": "LL", "template_ref": "custom:abc"}]
            }
        },
    )
    assert response.status_code == 422, response.text
    assert "custom:abc" not in response.text
    assert _context_events(mock_audit_log) == []


async def test_rejectsOverCap(app_client, db_session, mock_audit_log) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    contexts = [{"label": f"c{i}"} for i in range(31)]
    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"contexts_per_visit_type": {"new_patient": contexts}},
    )
    assert response.status_code == 422
    assert _context_events(mock_audit_log) == []


# ── Audit emission contract ───────────────────────────────────────────────


async def test_emitsCountOnlyAuditOnRealDiff(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "contexts_per_visit_type": {
                "new_patient": [
                    {"label": "SecretLL", "template_key": _BUILTIN_TEMPLATE},
                    {"label": "SecretBreast"},
                ]
            }
        },
    )
    assert response.status_code == 200, response.text

    rows = _context_events(mock_audit_log)
    assert len(rows) == 1
    payload = rows[0]
    assert payload["visit_types_touched"] == 1
    assert payload["contexts_added"] == 2
    assert payload["contexts_removed"] == 0
    assert payload["templates_attached"] == 1
    assert payload["templates_detached"] == 0
    assert "actor_id" in payload
    # No labels / keys / template names / ids in the audit row.
    blob = repr(payload)
    assert "SecretLL" not in blob
    assert "SecretBreast" not in blob
    assert _BUILTIN_TEMPLATE not in blob
    assert "ctx_" not in blob


async def test_noChangeSkipsAuditEmit(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    # First write mints ids; read them back so the second PUT is a no-op.
    first = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"contexts_per_visit_type": {"new_patient": [{"label": "LL"}]}},
    )
    same_map = first.json()["contexts_per_visit_type"]
    mock_audit_log.write_event.reset_mock()

    second = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"contexts_per_visit_type": same_map},
    )
    assert second.status_code == 200, second.text
    assert _context_events(mock_audit_log) == []


async def test_unrelatedFieldUpdateSkipsAuditEmit(
    app_client, db_session, mock_audit_log
) -> None:
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"contexts_per_visit_type": {"new_patient": [{"label": "LL"}]}},
    )
    mock_audit_log.write_event.reset_mock()

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"ui_theme": "dark"},
    )
    assert response.status_code == 200, response.text
    assert _context_events(mock_audit_log) == []
