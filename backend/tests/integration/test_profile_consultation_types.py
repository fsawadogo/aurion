# ruff: noqa: F401, F811
"""Integration tests for the consultation-types audit emission (#259).

The route handler at ``PUT /profile`` widens consultation_types to accept
custom clinician-authored labels alongside the four canonical defaults
("new_patient", "follow_up", "pre_op", "post_op"). When the list
actually changes, the route emits a single
``PROFILE_CONSULTATION_TYPES_UPDATED`` audit row carrying the count
deltas — NEVER the labels.

Properties asserted here:
  * The default-only update path still works (existing iOS clients).
  * Custom labels persist round-trip.
  * The 60-char + format gates reject pathological input with 422.
  * The 20-custom soft cap rejects with 422.
  * The audit row payload contains ONLY actor_id + the six count
    fields — never the type labels themselves.
  * Same-list updates emit zero rows.
  * Unrelated profile updates (e.g. ``ui_theme`` flip) don't emit
    ``PROFILE_CONSULTATION_TYPES_UPDATED``.
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


def _consultation_events(mock_audit_log) -> list[dict]:
    """Return the kwargs dicts of every PROFILE_CONSULTATION_TYPES_UPDATED
    row written during the test. We compare on full payload so the test
    also covers the no-PHI guarantee."""
    rows = []
    for call in mock_audit_log.write_event.call_args_list:
        if (
            call.kwargs.get("event_type")
            == AuditEventType.PROFILE_CONSULTATION_TYPES_UPDATED
        ):
            rows.append(call.kwargs)
    return rows


# ── Happy paths ─────────────────────────────────────────────────────────


async def test_acceptsDefaultsOnly(app_client, db_session, mock_audit_log) -> None:
    """AC-7 — the existing iOS path (defaults only) keeps working."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"consultation_types": ["new_patient", "follow_up", "pre_op"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consultation_types"] == ["new_patient", "follow_up", "pre_op"]


async def test_acceptsCustomTypes(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-7 — custom clinician-authored labels persist round-trip."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "follow_up",
                "LL new pt",
                "Breast",
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consultation_types"] == [
        "new_patient",
        "follow_up",
        "LL new pt",
        "Breast",
    ]


@pytest.mark.parametrize(
    "label",
    [
        "Limb Lengthening Cosmetic",  # 3 Title-Case descriptive words
        "Breast Reconstruction",
        "Marie Gdalevitch",  # no longer rejected — proper-noun gate is OFF
    ],
)
async def test_acceptsFullWordCustomTypes(
    app_client, db_session, mock_audit_log, label
) -> None:
    """Pilot "don't restrict" feedback: full descriptive multi-word,
    Title-Case labels persist round-trip. The proper-noun / full-name
    heuristic is OFF; only SSN / email / length still gate."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"consultation_types": ["new_patient", label]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["consultation_types"] == ["new_patient", label]


async def test_stripsWhitespaceAndDedupes(
    app_client, db_session, mock_audit_log
) -> None:
    """Leading/trailing whitespace is trimmed; duplicate canonical
    entries are dropped. Two customs that differ only in case are kept
    distinct by design."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "new_patient",  # exact dup → dropped
                "  Breast  ",  # whitespace → stripped
                "Breast",  # post-strip dup → dropped
                "BREAST",  # case-distinct → kept
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consultation_types"] == ["new_patient", "Breast", "BREAST"]


# ── Format gates ─────────────────────────────────────────────────────────


async def test_rejectsTooLongType(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-4 — labels longer than 60 chars rejected with 422."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "X" * 61,
            ],
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "bad_value,expected_phrase",
    [
        ("123456789", "SSN"),
        ("123-45-6789", "SSN"),
        ("perry@clinic.lan", "email"),
    ],
)
async def test_rejectsPHIShapedTypes(
    app_client, db_session, mock_audit_log, bad_value, expected_phrase
) -> None:
    """AC-4 — SSN / email shapes are rejected at the Pydantic boundary,
    and the rejected value never echoes in the response body
    (``hide_input_in_errors=True``).

    The proper-noun / full-name heuristic is intentionally OFF now (pilot
    "don't restrict" feedback) — a Title-Case label like "Marie
    Gdalevitch" is no longer rejected; see
    ``test_acceptsFullWordCustomTypes``. SSN / email / length still gate."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                bad_value,
            ],
        },
    )
    assert response.status_code == 422
    # The error body must mention the reason but NOT the value.
    text = response.text
    assert expected_phrase in text or "consultation type" in text
    assert bad_value not in text


async def test_rejectsTooManyCustomTypes(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-3 — more than 20 custom types rejects with 422 before the
    audit emit fires."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    twenty_one_customs = [f"custom_{i}" for i in range(21)]
    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={"consultation_types": ["new_patient", *twenty_one_customs]},
    )
    assert response.status_code == 422
    rows = _consultation_events(mock_audit_log)
    assert rows == [], "rejected request must not emit audit row"


# ── Audit emission contract (AC-8) ───────────────────────────────────────


async def test_emitsAuditWithCountDeltasOnly(
    app_client, db_session, mock_audit_log
) -> None:
    """AC-8 — exactly one audit row with the six count fields plus
    actor_id, and NEVER the labels themselves."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "follow_up",
                "pre_op",  # default added vs the seeded ["new_patient", "follow_up"]
                "Breast",  # custom added
                "LL new pt",  # custom added
            ],
        },
    )
    assert response.status_code == 200, response.text

    rows = _consultation_events(mock_audit_log)
    assert len(rows) == 1, f"expected exactly 1 audit row, got {len(rows)}"
    payload = rows[0]
    # Seeded defaults are ["new_patient", "follow_up"] (see
    # profile/service.py::get_or_create_profile).
    assert payload["count_before"] == 2
    assert payload["count_after"] == 5
    assert payload["defaults_added"] == 1
    assert payload["defaults_removed"] == 0
    assert payload["customs_added"] == 2
    assert payload["customs_removed"] == 0
    assert "actor_id" in payload
    # The labels themselves must NEVER appear in the audit payload.
    payload_str = repr(payload)
    assert "Breast" not in payload_str
    assert "LL new pt" not in payload_str
    assert "new_patient" not in payload_str
    assert "follow_up" not in payload_str


async def test_emitsAuditOnCustomRemoval(
    app_client, db_session, mock_audit_log
) -> None:
    """Removing a custom emits an audit row with the inverted delta."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    # Seed: add two customs.
    await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "follow_up",
                "Breast",
                "LL new pt",
            ],
        },
    )
    mock_audit_log.write_event.reset_mock()

    # Drop one custom.
    response = await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "follow_up",
                "Breast",
            ],
        },
    )
    assert response.status_code == 200, response.text
    rows = _consultation_events(mock_audit_log)
    assert len(rows) == 1
    payload = rows[0]
    assert payload["count_before"] == 4
    assert payload["count_after"] == 3
    assert payload["customs_added"] == 0
    assert payload["customs_removed"] == 1
    assert payload["defaults_added"] == 0
    assert payload["defaults_removed"] == 0


async def test_noChange_skipsAuditEmit(
    app_client, db_session, mock_audit_log
) -> None:
    """Sending the same list twice emits exactly one audit row (on the
    first call). The second call's diff is empty and skips the emit."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    body = {
        "consultation_types": [
            "new_patient",
            "follow_up",
            "Breast",
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
    rows = _consultation_events(mock_audit_log)
    assert rows == [], (
        "no-change update must not emit PROFILE_CONSULTATION_TYPES_UPDATED"
    )


async def test_unrelatedFieldUpdate_skipsAuditEmit(
    app_client, db_session, mock_audit_log
) -> None:
    """A profile update that doesn't include ``consultation_types``
    (e.g. flipping ``ui_theme``) must not emit
    ``PROFILE_CONSULTATION_TYPES_UPDATED`` even when the persisted
    types list is non-empty."""
    _user_id, email = await seed_user(db_session)
    access = await _login(app_client, email)

    # Seed a non-default list.
    await app_client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "consultation_types": [
                "new_patient",
                "follow_up",
                "Breast",
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
    rows = _consultation_events(mock_audit_log)
    assert rows == [], (
        "ui_theme update must not emit PROFILE_CONSULTATION_TYPES_UPDATED"
    )
