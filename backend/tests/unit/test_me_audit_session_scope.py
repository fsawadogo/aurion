"""VIS-06 (#748) — a clinician can see their own session's FULL audit trail.

Every event the pipeline writes from its background task carries no actor:
``recording_started``, ``stage1_started``, ``transcription_complete``,
``video_import_complete``, ``stage2_started``, ``visual_enrichment_complete``.
There is no human in the loop to attribute them to.

``/me/audit`` filtered on ``actor_id == caller``, so every one of those was
dropped. A clinician opening My Activity saw consent and nothing else — and a
session that captured 182 frames and discarded 180 looked identical to one
that captured none. That is why the enrichment bug survived weeks of use.

The actor filter was also carrying the ownership guarantee implicitly, so
these tests pin BOTH halves: the pipeline events are now visible, and someone
else's session still 404s.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _event(event_type: str, **fields):
    """A DynamoDB audit row as `apply_audit_filters` sees it."""
    row = {
        "event_type": event_type,
        "event_timestamp": "2026-08-14T02:18:06.224",
        "session_id": SESSION_ID,
    }
    row.update(fields)
    return row


CALLER = uuid.uuid4()
SESSION_ID = str(uuid.uuid4())

# What the pipeline actually writes for one imported encounter. Only the two
# human-initiated events carry an actor.
_SESSION_TRAIL = [
    _event("consent_attested", actor_id=str(CALLER), method="attested"),
    _event("video_import_started", actor_id=str(CALLER)),
    _event("recording_started"),
    _event("stage1_started"),
    _event("transcription_complete"),
    _event("video_import_complete"),
    _event("stage2_started"),
    _event("visual_enrichment_complete"),
]


class _Audit:
    def __init__(self, events):
        self._events = events

    async def get_session_events(self, _session_id):
        return self._events


@pytest.mark.asyncio
async def test_session_scoped_query_returns_the_pipeline_events(monkeypatch):
    """The regression: six actor-less events were invisible."""
    from app.api.v1 import me as route

    monkeypatch.setattr(route, "get_audit_log_service", lambda: _Audit(_SESSION_TRAIL))
    monkeypatch.setattr(
        route, "get_owned_session_or_404", _owns
    )

    # Every param passed explicitly: called directly, the `Query(None)`
    # defaults are Query OBJECTS, not None, and would read as truthy.
    resp = await route.get_my_audit_log(
        date_from=None, date_to=None, event_type=None,
        session_id=SESSION_ID, page=1, page_size=50,
        user=SimpleNamespace(user_id=CALLER),
        db=object(),
    )

    returned = {i.event_type for i in resp.items}
    assert "stage1_started" in returned, (
        "pipeline events still hidden — the actor filter is still applied to "
        "a session-scoped query"
    )
    assert returned == {e["event_type"] for e in _SESSION_TRAIL}
    assert resp.total == len(_SESSION_TRAIL)


@pytest.mark.asyncio
async def test_another_clinicians_session_still_404s(monkeypatch):
    """Ownership was implicit in the actor filter; it must now be explicit.

    Without this the change would trade a usability bug for a PHI leak.
    """
    from app.api.v1 import me as route

    monkeypatch.setattr(route, "get_audit_log_service", lambda: _Audit(_SESSION_TRAIL))

    async def _denies(*_a, **_kw):
        raise HTTPException(status_code=404, detail="Session not found")

    monkeypatch.setattr(route, "get_owned_session_or_404", _denies)

    with pytest.raises(HTTPException) as exc:
        await route.get_my_audit_log(
            date_from=None, date_to=None, event_type=None,
            session_id=str(uuid.uuid4()), page=1, page_size=50,
            user=SimpleNamespace(user_id=CALLER),
            db=object(),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unscoped_scan_still_filters_by_actor(monkeypatch):
    """No session to prove ownership of → actor identity is the only sound scope."""
    from app.api.v1 import me as route

    other = str(uuid.uuid4())
    mixed = [
        _event("note_exported", actor_id=str(CALLER)),
        _event("note_exported", actor_id=other),
        # Actor-less: correctly invisible in an unbounded scan.
        _event("stage1_started"),
    ]

    monkeypatch.setattr(route, "get_audit_log_service", lambda: _Audit([]))
    monkeypatch.setattr(
        route, "scan_audit_events", _scan_returning(mixed)
    )

    resp = await route.get_my_audit_log(
        date_from=None, date_to=None, event_type=None,
        session_id=None, page=1, page_size=50,
        user=SimpleNamespace(user_id=CALLER), db=object(),
    )

    assert resp.total == 1, "unbounded scan must stay scoped to the caller"


async def _owns(*_a, **_kw):
    return SimpleNamespace(id=SESSION_ID)


def _scan_returning(events):
    async def _scan(_audit):
        return events

    return _scan
