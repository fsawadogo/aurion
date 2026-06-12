"""Alert service — persist + retrieve operational alerts (issue #76).

A trigger site (e.g. a Stage 1 failure handler) calls
``AlertService.publish(...)``; an ADMIN / COMPLIANCE_OFFICER reads via
``AlertService.list(...)`` from ``GET /api/v1/admin/alerts``.

Best-effort semantics: callers should wrap ``publish`` in a try/except
so an alert-DB hiccup never breaks the underlying audited code path.
"""

from __future__ import annotations

import enum
import logging
import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.database import async_session_factory
from app.core.models import AlertModel
from app.modules.alerts.email_sink import schedule_critical_email_notification
from app.modules.alerts.slack_sink import schedule_critical_notification

logger = logging.getLogger("aurion.alerts")


class AlertSeverity(str, enum.Enum):
    """Stable string values — persisted in `alerts.severity` and emitted
    on the wire, so downgrades / renames are breaking. Keep additive."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertService:
    """Thin service wrapper around the `alerts` table.

    Constructor takes nothing — the session is injected per-call so the
    service can be a singleton if needed in the future (matches the
    audit_log/eval service shape).
    """

    async def publish(
        self,
        db: AsyncSession,
        *,
        alert_type: str,
        severity: AlertSeverity,
        source: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Insert an alert row; return its id.

        Callers are expected to be in a request-scoped session that the
        framework commits on success. The trigger-site try/except should
        catch any SQL error so the surrounding audited code path stays
        independent of alerts.
        """
        record = AlertModel(
            id=uuid.uuid4(),
            alert_type=alert_type,
            severity=severity.value,
            source=source,
            message=message,
            alert_metadata=metadata,
            created_at=utcnow(),
        )
        db.add(record)
        await db.flush()
        logger.info(
            "alert published: type=%s severity=%s source=%s",
            alert_type,
            severity.value,
            source,
        )
        # #76 delivery sinks — fire-and-forget for CRITICAL only; each is a
        # no-op until its own config is provisioned (Slack webhook /
        # ALERT_EMAIL_RECIPIENTS). Plain strings cross into the detached
        # tasks, never the session.
        schedule_critical_notification(
            alert_type=alert_type,
            severity=severity.value,
            source=source,
            message=message,
        )
        schedule_critical_email_notification(
            alert_type=alert_type,
            severity=severity.value,
            source=source,
            message=message,
        )
        return record.id

    async def list(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,  # "open" | "acknowledged"
        severity: AlertSeverity | None = None,
        alert_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AlertModel]:
        """Paginated list, newest first. Filters are AND-combined."""
        stmt = select(AlertModel).order_by(desc(AlertModel.created_at))
        if status == "open":
            stmt = stmt.where(AlertModel.acknowledged_at.is_(None))
        elif status == "acknowledged":
            stmt = stmt.where(AlertModel.acknowledged_at.is_not(None))
        if severity is not None:
            stmt = stmt.where(AlertModel.severity == severity.value)
        if alert_type is not None:
            stmt = stmt.where(AlertModel.alert_type == alert_type)
        stmt = stmt.limit(min(max(limit, 1), 200)).offset(max(offset, 0))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def acknowledge(
        self,
        db: AsyncSession,
        alert_id: uuid.UUID,
        *,
        acknowledged_by: uuid.UUID,
    ) -> AlertModel | None:
        """Mark an alert acknowledged; return the row, or None if absent.

        Idempotent: an already-acknowledged alert is returned unchanged
        (the FIRST acknowledger is preserved — a second click must not
        rewrite who took ownership of the alert).
        """
        result = await db.execute(
            select(AlertModel).where(AlertModel.id == alert_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.acknowledged_at is None:
            row.acknowledged_at = utcnow()
            row.acknowledged_by = acknowledged_by
            await db.flush()
        return row


_INSTANCE: AlertService | None = None


def get_alert_service() -> AlertService:
    """Lazy singleton — mirrors the audit_log/eval service factory shape."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AlertService()
    return _INSTANCE


async def try_publish_alert(
    *,
    alert_type: str,
    severity: AlertSeverity,
    source: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget alert publish for trigger sites without an existing
    AsyncSession.

    Opens its own short-lived session, commits, and swallows any errors
    (logged with ``exc_info``) so an alerts-DB hiccup never alters the
    audited code path it sits next to. Use this from ``transcribe_audio``,
    ``caption_frames``, Stage 2 background jobs — anywhere the
    surrounding code can't / shouldn't take an extra dependency on the
    request's DB session.

    Callers that already have a session should call
    ``get_alert_service().publish(db, ...)`` directly so the alert lands
    in the same transaction as the surrounding work.
    """
    try:
        async with async_session_factory() as db:
            await get_alert_service().publish(
                db,
                alert_type=alert_type,
                severity=severity,
                source=source,
                message=message,
                metadata=metadata,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — best-effort by design
        logger.warning(
            "alert publish failed: type=%s source=%s",
            alert_type,
            source,
            exc_info=True,
        )
