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
    build_masking_csv,
    build_retention_csv,
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
    @pytest.mark.parametrize("rtype", list(ReportType))
    async def test_generate_supports_every_report_type(self, rtype) -> None:
        """#77: all three types are wired — audit, masking, retention.
        (Replaces the foundation-era rejects-unwired test.)"""
        svc = ComplianceReportsService()
        db = _mock_db()
        record = await svc.generate(
            db,
            report_type=rtype,
            events=[],
            since=None,
            until=None,
            generated_by=None,
        )
        assert record.report_type == rtype.value
        assert record.sha256 == hashlib.sha256(record.content_bytes).hexdigest()
        # Even an empty report carries its header row.
        assert record.content_bytes.startswith(b"session_id,event_timestamp,event_type")

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


class TestMaskingBuilder:
    def test_filters_to_masking_events_and_types_columns(self) -> None:
        now = datetime.now(timezone.utc)
        events = [
            {**_evt("s1", now, "clip_uploaded"), "masking_status": "success",
             "frames_total": 7, "frames_with_faces": 7, "faces_blurred": 7},
            _evt("s1", now, "consent_confirmed"),          # not masking-relevant
            {**_evt("s2", now, "clip_dropped"), "reason": "masking_failed",
             "origin": "ios"},
            {**_evt("s3", now, "clip_dropped"), "reason": "ring_empty"},  # excluded
        ]
        body = build_masking_csv(events).decode("utf-8")
        lines = body.strip().splitlines()
        header, rows = lines[0], lines[1:]
        assert "masking_status" in header
        assert "faces_blurred" in header
        assert len(rows) == 2                      # clip_uploaded + masking drop
        assert "clip_uploaded" in rows[0] and ",7," in rows[0]
        assert "masking_failed" in rows[1]
        assert all("ring_empty" not in r for r in rows)
        assert all("consent_confirmed" not in r for r in rows)


class TestRetentionBuilder:
    def test_filters_to_retention_lifecycle(self) -> None:
        now = datetime.now(timezone.utc)
        events = [
            {**_evt("s1", now, "audio_purged"), "audio_count": 1},
            {**_evt("s1", now, "evidence_downloaded"),
             "evidence_kind": "session_media", "audio_count": 1, "clip_count": 3},
            {**_evt("s1", now, "note_exported"), "format": "docx"},
            _evt("s1", now, "recording_started"),  # not retention-relevant
        ]
        body = build_retention_csv(events).decode("utf-8")
        lines = body.strip().splitlines()
        header, rows = lines[0], lines[1:]
        assert "evidence_kind" in header and "clip_count" in header
        assert len(rows) == 3
        assert any("audio_purged" in r for r in rows)
        assert any("session_media" in r and ",3," in r for r in rows)
        assert any("docx" in r for r in rows)
        assert all("recording_started" not in r for r in rows)

    def test_window_applies_to_all_types(self) -> None:
        """generate() filters the window BEFORE the builder for every type —
        spot-check via the public builder + _filter_window composition."""
        now = datetime.now(timezone.utc)
        old_evt = {**_evt("s1", now - timedelta(days=40), "audio_purged")}
        new_evt = {**_evt("s1", now, "audio_purged")}
        windowed = _filter_window([old_evt, new_evt], now - timedelta(days=7), None)
        body = build_retention_csv(windowed).decode("utf-8")
        assert body.count("audio_purged") == 1
