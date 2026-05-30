"""Unit tests for ComplianceReportsService (issue #77).

AsyncMock pattern — matches test_alert_service.py / test_provider_usage.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import ComplianceReportModel
from app.modules.compliance.reports_service import (
    ComplianceReportsService,
    ReportType,
    _filter_window,
    build_audit_csv,
    get_compliance_reports_service,
)


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _evt(session_id: str, ts: datetime, event_type: str = "consent_confirmed") -> dict:
    return {
        "session_id": session_id,
        "event_timestamp": ts.isoformat(),
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "actor": "system",
        "details_extra": "hello",
    }


class TestFilterWindow:
    def test_no_bounds_returns_all(self) -> None:
        now = datetime.now(timezone.utc)
        events = [_evt("s1", now), _evt("s2", now - timedelta(days=1))]
        assert _filter_window(events, None, None) == events

    def test_since_inclusive(self) -> None:
        now = datetime.now(timezone.utc)
        events = [_evt("old", now - timedelta(days=10)), _evt("new", now)]
        out = _filter_window(events, since=now - timedelta(days=1), until=None)
        assert len(out) == 1
        assert out[0]["session_id"] == "new"

    def test_until_inclusive(self) -> None:
        now = datetime.now(timezone.utc)
        events = [_evt("a", now - timedelta(days=2)), _evt("b", now)]
        out = _filter_window(events, since=None, until=now - timedelta(days=1))
        assert len(out) == 1
        assert out[0]["session_id"] == "a"

    def test_malformed_timestamp_skipped(self) -> None:
        events = [{"event_timestamp": "not-a-date", "session_id": "x"}]
        out = _filter_window(events, since=datetime.now(timezone.utc), until=None)
        assert out == []


class TestBuildAuditCsv:
    def test_header_and_row(self) -> None:
        now = datetime.now(timezone.utc)
        events = [_evt("s1", now)]
        csv_bytes = build_audit_csv(events)
        text = csv_bytes.decode("utf-8")
        # Header
        assert text.splitlines()[0] == (
            "session_id,event_timestamp,event_type,event_id,details"
        )
        # Row contains session id and event type
        assert "s1" in text
        assert "consent_confirmed" in text

    def test_extra_fields_serialized_to_details_json(self) -> None:
        now = datetime.now(timezone.utc)
        csv_bytes = build_audit_csv([_evt("s1", now)])
        text = csv_bytes.decode("utf-8")
        # details column carries any non-core fields as JSON
        assert "details_extra" in text


class TestGenerate:
    @pytest.mark.asyncio
    async def test_generate_persists_and_signs(self) -> None:
        svc = ComplianceReportsService()
        db = _mock_db()
        now = datetime.now(timezone.utc)
        events = [_evt("s1", now)]

        record = await svc.generate(
            db,
            report_type=ReportType.AUDIT,
            events=events,
            since=None,
            until=None,
            generated_by=uuid.uuid4(),
        )

        assert isinstance(record, ComplianceReportModel)
        assert record.report_type == "audit"
        assert record.byte_size == len(record.content_bytes)
        # sha256 matches the canonical hash of the bytes
        assert (
            record.sha256
            == hashlib.sha256(record.content_bytes).hexdigest()
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_rejects_unwired_report_type(self) -> None:
        svc = ComplianceReportsService()
        db = _mock_db()
        with pytest.raises(NotImplementedError):
            await svc.generate(
                db,
                report_type=ReportType.MASKING,
                events=[],
                since=None,
                until=None,
                generated_by=None,
            )

    @pytest.mark.asyncio
    async def test_generate_applies_window(self) -> None:
        svc = ComplianceReportsService()
        db = _mock_db()
        now = datetime.now(timezone.utc)
        events = [
            _evt("old", now - timedelta(days=10)),
            _evt("recent", now),
        ]
        record = await svc.generate(
            db,
            report_type=ReportType.AUDIT,
            events=events,
            since=now - timedelta(days=1),
            until=None,
            generated_by=None,
        )
        text = record.content_bytes.decode("utf-8")
        assert "recent" in text
        assert "old" not in text


class TestServiceFactory:
    def test_get_compliance_reports_service_is_singleton(self) -> None:
        a = get_compliance_reports_service()
        b = get_compliance_reports_service()
        assert a is b
