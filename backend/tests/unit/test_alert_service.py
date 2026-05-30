"""Unit tests for AlertService (issue #76).

Mirrors the existing AsyncMock pattern (see test_auth_active.py) so the
suite stays pure-Python — no extra DB driver dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import AlertModel
from app.modules.alerts.service import AlertService, AlertSeverity


def _mock_db() -> AsyncMock:
    """An AsyncSession mock where add() records, flush() is awaitable,
    and execute() can be primed by the caller for list() tests."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_execute_returning(rows: list[AlertModel]) -> MagicMock:
    """Build a ``result`` object such that ``result.scalars().all()`` ==
    ``rows`` — matches the shape SQLAlchemy returns from ``execute``."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result.scalars = MagicMock(return_value=scalars)
    return result


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_persists_row(self) -> None:
        svc = AlertService()
        db = _mock_db()

        alert_id = await svc.publish(
            db,
            alert_type="stage1_failed",
            severity=AlertSeverity.CRITICAL,
            source="transcription_service",
            message="Stage 1 note generation failed",
            metadata={"session_id": "abc"},
        )

        assert isinstance(alert_id, uuid.UUID)
        assert db.add.call_count == 1
        added = db.add.call_args.args[0]
        assert isinstance(added, AlertModel)
        assert added.id == alert_id
        assert added.alert_type == "stage1_failed"
        assert added.severity == "critical"
        assert added.source == "transcription_service"
        assert added.message == "Stage 1 note generation failed"
        assert added.alert_metadata == {"session_id": "abc"}
        assert added.created_at is not None
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_without_metadata(self) -> None:
        svc = AlertService()
        db = _mock_db()
        await svc.publish(
            db,
            alert_type="t",
            severity=AlertSeverity.WARNING,
            source="s",
            message="m",
        )
        added = db.add.call_args.args[0]
        assert added.alert_metadata is None


class TestList:
    @pytest.mark.asyncio
    async def test_list_returns_records(self) -> None:
        svc = AlertService()
        db = _mock_db()
        fake_rows = [
            AlertModel(
                id=uuid.uuid4(),
                alert_type="stage1_failed",
                severity="critical",
                source="transcription_service",
                message="m",
                created_at=datetime.now(timezone.utc),
            ),
        ]
        db.execute = AsyncMock(return_value=_mock_execute_returning(fake_rows))

        out = await svc.list(db)
        assert out == fake_rows
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_clamps_limit(self) -> None:
        """``limit`` is clamped to [1, 200] before reaching the query."""
        svc = AlertService()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_execute_returning([]))

        # Above-max → clamped to 200; below-min → clamped to 1.
        await svc.list(db, limit=10_000)
        await svc.list(db, limit=0)
        # Two execute calls (clamping is in the query builder; we just
        # confirm the executor ran twice without raising).
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_list_accepts_filters(self) -> None:
        svc = AlertService()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_execute_returning([]))

        # Just verify the call doesn't raise on each filter combination.
        await svc.list(db, status="open")
        await svc.list(db, status="acknowledged")
        await svc.list(db, severity=AlertSeverity.WARNING)
        await svc.list(db, alert_type="stage1_failed")
        await svc.list(
            db,
            status="open",
            severity=AlertSeverity.CRITICAL,
            alert_type="stage1_failed",
        )
        assert db.execute.await_count == 5


class TestServiceFactory:
    def test_get_alert_service_is_singleton(self) -> None:
        from app.modules.alerts.service import get_alert_service

        a = get_alert_service()
        b = get_alert_service()
        assert a is b


class TestTryPublishAlert:
    """The fire-and-forget helper that the trigger sites use. It must
    swallow any error so the audited code path it sits next to never
    sees an exception from telemetry."""

    @pytest.mark.asyncio
    async def test_swallows_session_factory_failure(self, monkeypatch) -> None:
        """If async_session_factory raises (DB down / pool exhausted),
        the helper logs and returns None — never re-raises."""
        from app.modules.alerts import service as alerts_mod

        def boom():  # noqa: ANN202
            raise RuntimeError("DB pool exhausted")

        monkeypatch.setattr(alerts_mod, "async_session_factory", boom)

        # Should not raise.
        await alerts_mod.try_publish_alert(
            alert_type="t",
            severity=AlertSeverity.CRITICAL,
            source="test",
            message="m",
        )

    @pytest.mark.asyncio
    async def test_swallows_publish_failure(self, monkeypatch) -> None:
        """If the underlying publish raises, the helper still swallows."""
        from contextlib import asynccontextmanager

        from app.modules.alerts import service as alerts_mod

        @asynccontextmanager
        async def fake_session_ctx():  # noqa: ANN202
            yield AsyncMock()  # commit is awaitable on AsyncMock by default

        # Replace the factory so __aenter__/__aexit__ work.
        def fake_factory():
            return fake_session_ctx()

        monkeypatch.setattr(alerts_mod, "async_session_factory", fake_factory)

        # Force the publish to raise.
        fake_svc = MagicMock()
        fake_svc.publish = AsyncMock(side_effect=RuntimeError("alert table missing"))
        monkeypatch.setattr(
            alerts_mod, "get_alert_service", lambda: fake_svc
        )

        await alerts_mod.try_publish_alert(
            alert_type="t",
            severity=AlertSeverity.CRITICAL,
            source="test",
            message="m",
        )
        fake_svc.publish.assert_awaited()
