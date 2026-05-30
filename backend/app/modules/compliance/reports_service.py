"""Compliance reports service (issue #77 foundation).

Generates a persisted, sha256-signed CSV snapshot of compliance-relevant
audit data so a clinic can hand an institution a verifiable archive.
Foundation wires the ``audit`` report type; ``masking`` + ``retention``
follow the same shape and land as follow-ups.
"""

from __future__ import annotations

import csv
import enum
import hashlib
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import ComplianceReportModel

logger = logging.getLogger("aurion.compliance")


class ReportType(str, enum.Enum):
    """Stable string values — persisted in `compliance_reports.report_type`."""

    AUDIT = "audit"
    # Wired in follow-ups:
    MASKING = "masking"
    RETENTION = "retention"


def _filter_window(events: list[dict[str, Any]], since: datetime | None, until: datetime | None) -> list[dict[str, Any]]:
    if since is None and until is None:
        return events
    out: list[dict[str, Any]] = []
    for evt in events:
        ts_raw = evt.get("event_timestamp")
        if ts_raw is None:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue
        out.append(evt)
    return out


def build_audit_csv(events: list[dict[str, Any]]) -> bytes:
    """Byte-identical to the manual ``/admin/audit/export`` shape so a
    persisted report and an ad-hoc export agree."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["session_id", "event_timestamp", "event_type", "event_id", "details"]
    )
    for evt in events:
        details = {
            k: v
            for k, v in evt.items()
            if k not in ("session_id", "event_timestamp", "event_type", "event_id")
        }
        writer.writerow(
            [
                evt.get("session_id", ""),
                evt.get("event_timestamp", ""),
                evt.get("event_type", ""),
                evt.get("event_id", ""),
                json.dumps(details),
            ]
        )
    return buf.getvalue().encode("utf-8")


class ComplianceReportsService:
    """Thin service around the ``compliance_reports`` table."""

    async def generate(
        self,
        db: AsyncSession,
        *,
        report_type: ReportType,
        events: list[dict[str, Any]],
        since: datetime | None,
        until: datetime | None,
        generated_by: uuid.UUID | None,
    ) -> ComplianceReportModel:
        """Build the CSV payload, hash it, persist a row, return it.

        Callers provide ``events`` so this method stays storage-agnostic
        (the audit log lives in DynamoDB; tests can pass a fixture list).
        The caller filters to the relevant set before passing — but we
        also apply the window here so the persisted bytes correspond
        to exactly the metadata's ``since``/``until``.
        """
        if report_type != ReportType.AUDIT:
            # Other types follow in a follow-up PR; explicit error is
            # better than silently producing an empty CSV.
            raise NotImplementedError(
                f"report_type={report_type.value} not wired yet "
                f"(foundation supports 'audit' only)"
            )

        filtered = _filter_window(events, since, until)
        content_bytes = build_audit_csv(filtered)
        sha256 = hashlib.sha256(content_bytes).hexdigest()

        record = ComplianceReportModel(
            id=uuid.uuid4(),
            report_type=report_type.value,
            since=since,
            until=until,
            generated_at=utcnow(),
            generated_by=generated_by,
            content_bytes=content_bytes,
            sha256=sha256,
            byte_size=len(content_bytes),
        )
        db.add(record)
        await db.flush()
        logger.info(
            "compliance report generated: type=%s rows=%d bytes=%d sha256=%s",
            report_type.value,
            len(filtered),
            len(content_bytes),
            sha256[:12] + "…",
        )
        return record

    async def list(
        self,
        db: AsyncSession,
        *,
        report_type: ReportType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ComplianceReportModel]:
        stmt = select(ComplianceReportModel).order_by(
            desc(ComplianceReportModel.generated_at)
        )
        if report_type is not None:
            stmt = stmt.where(ComplianceReportModel.report_type == report_type.value)
        stmt = stmt.limit(min(max(limit, 1), 200)).offset(max(offset, 0))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get(
        self, db: AsyncSession, report_id: uuid.UUID
    ) -> ComplianceReportModel | None:
        result = await db.execute(
            select(ComplianceReportModel).where(
                ComplianceReportModel.id == report_id
            )
        )
        return result.scalar_one_or_none()


_INSTANCE: ComplianceReportsService | None = None


def get_compliance_reports_service() -> ComplianceReportsService:
    """Lazy singleton — matches the alerts / provider-usage factory shape."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ComplianceReportsService()
    return _INSTANCE
