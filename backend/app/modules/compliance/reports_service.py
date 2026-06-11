"""Compliance reports service (issue #77 foundation).

Generates a persisted, sha256-signed CSV snapshot of compliance-relevant
audit data so a clinic can hand an institution a verifiable archive.
Three report types (#77): ``audit`` (the full trail), ``masking`` (the
PHI-masking proof per session — Law 25's "show me every frame was masked"
artifact), and ``retention`` (the purge/retained-media-access lifecycle).
Scheduled generation + delivery land post-SES (#399).
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


def dump_details(details: dict[str, Any]) -> str:
    """JSON-serialize an audit event's detail fields for a CSV cell.

    DynamoDB (boto3 resource) returns every number as ``decimal.Decimal``,
    which stock ``json.dumps`` refuses — this crashed all three report
    builders (and the audit CSV export) the moment the table scan started
    returning real rows (#413 IAM fix made the latent bug live).
    ``default=str`` renders Decimals (and any other exotic type) as their
    string form — the right trade for a human-audited CSV cell.
    """
    return json.dumps(details, default=str)


class ReportType(str, enum.Enum):
    """Stable string values — persisted in `compliance_reports.report_type`."""

    AUDIT = "audit"
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


# ── Masking report (#77) ─────────────────────────────────────────────────────
#
# The PHI-masking proof: every masking confirmation (frames + clips +
# screen), every vision-side rejection, and every client-side drop whose
# reason was a masking failure. The typed columns are the fields a
# compliance officer checks row-by-row; everything else rides in `details`.

_MASKING_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "masking_confirmed",
        "clip_masked",
        "frame_uploaded",
        "clip_uploaded",
        "screen_frame_processed",
        "vision_frame_failed",
    }
)

_MASKING_TYPED_COLUMNS = (
    "masking_status",
    "frame_type",
    "frames_total",
    "frames_with_faces",
    "faces_blurred",
    "phi_regions_redacted",
)


def _is_masking_relevant(evt: dict[str, Any]) -> bool:
    etype = str(evt.get("event_type", ""))
    if etype in _MASKING_EVENT_TYPES:
        return True
    # Drop telemetry counts as masking evidence ONLY when the drop reason
    # was a masking failure (ring_empty/upload_failed etc. are not).
    return etype == "clip_dropped" and evt.get("reason") == "masking_failed"


def build_masking_csv(events: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["session_id", "event_timestamp", "event_type", *_MASKING_TYPED_COLUMNS, "details"]
    )
    for evt in events:
        if not _is_masking_relevant(evt):
            continue
        details = {
            k: v
            for k, v in evt.items()
            if k
            not in (
                "session_id",
                "event_timestamp",
                "event_type",
                "event_id",
                *_MASKING_TYPED_COLUMNS,
            )
        }
        writer.writerow(
            [
                evt.get("session_id", ""),
                evt.get("event_timestamp", ""),
                evt.get("event_type", ""),
                *(evt.get(c, "") for c in _MASKING_TYPED_COLUMNS),
                dump_details(details),
            ]
        )
    return buf.getvalue().encode("utf-8")


# ── Retention report (#77) ───────────────────────────────────────────────────
#
# The purge / retained-media lifecycle: raw-media purges (audio, frames,
# whole sessions), cleanup failures, eval-frame migrations, exports, and
# every retained-media access (replay / download) — the rows an
# institution audits for "data deleted on schedule, every access logged".

_RETENTION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "audio_purged",
        "frames_purged",
        "session_purged",
        "session_discarded",
        "cleanup_partial_failure",
        "eval_frames_migrated",
        "evidence_replayed",
        "evidence_downloaded",
        "note_exported",
    }
)

_RETENTION_TYPED_COLUMNS = ("evidence_kind", "audio_count", "clip_count", "format")


def build_retention_csv(events: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["session_id", "event_timestamp", "event_type", *_RETENTION_TYPED_COLUMNS, "details"]
    )
    for evt in events:
        if str(evt.get("event_type", "")) not in _RETENTION_EVENT_TYPES:
            continue
        details = {
            k: v
            for k, v in evt.items()
            if k
            not in (
                "session_id",
                "event_timestamp",
                "event_type",
                "event_id",
                *_RETENTION_TYPED_COLUMNS,
            )
        }
        writer.writerow(
            [
                evt.get("session_id", ""),
                evt.get("event_timestamp", ""),
                evt.get("event_type", ""),
                *(evt.get(c, "") for c in _RETENTION_TYPED_COLUMNS),
                dump_details(details),
            ]
        )
    return buf.getvalue().encode("utf-8")


_BUILDERS = {
    # ReportType → CSV builder over the (window-filtered) audit events.
    # Populated after the function definitions below.
}


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
                dump_details(details),
            ]
        )
    return buf.getvalue().encode("utf-8")


_BUILDERS.update(
    {
        ReportType.AUDIT: build_audit_csv,
        ReportType.MASKING: build_masking_csv,
        ReportType.RETENTION: build_retention_csv,
    }
)


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
        builder = _BUILDERS[report_type]
        filtered = _filter_window(events, since, until)
        content_bytes = builder(filtered)
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
