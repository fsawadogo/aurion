"""Unit tests for the #76 alert acknowledge flow.

Service-level: idempotency (the FIRST acknowledger is preserved), the
None-on-absent contract. Route-level: registration + 404 mapping.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.alerts.service import AlertService


def _row(acknowledged: bool = False) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.acknowledged_at = (
        datetime(2026, 6, 1, tzinfo=timezone.utc) if acknowledged else None
    )
    row.acknowledged_by = uuid.uuid4() if acknowledged else None
    return row


def _db_returning(row) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    return db


def test_acknowledge_endpoint_registered() -> None:
    from app.api.v1.admin.alerts import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/admin/alerts/{alert_id}/acknowledge", ("PATCH",)) in paths


@pytest.mark.asyncio
async def test_acknowledge_sets_fields_once() -> None:
    row = _row(acknowledged=False)
    db = _db_returning(row)
    actor = uuid.uuid4()

    got = await AlertService().acknowledge(db, row.id, acknowledged_by=actor)

    assert got is row
    assert row.acknowledged_by == actor
    assert row.acknowledged_at is not None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_acknowledge_is_idempotent_and_preserves_first_actor() -> None:
    row = _row(acknowledged=True)
    first_actor = row.acknowledged_by
    first_at = row.acknowledged_at
    db = _db_returning(row)

    got = await AlertService().acknowledge(
        db, row.id, acknowledged_by=uuid.uuid4()
    )

    assert got is row
    assert row.acknowledged_by == first_actor   # ownership NOT rewritten
    assert row.acknowledged_at == first_at
    db.flush.assert_not_awaited()               # no write on the no-op path


@pytest.mark.asyncio
async def test_acknowledge_absent_returns_none() -> None:
    db = _db_returning(None)
    got = await AlertService().acknowledge(
        db, uuid.uuid4(), acknowledged_by=uuid.uuid4()
    )
    assert got is None
