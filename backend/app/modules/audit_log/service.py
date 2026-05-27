"""DynamoDB audit log — append-only, no update or delete. Ever.

Every session state transition, AI call, config change, and data lifecycle
event is written here. The write interface intentionally has no update or
delete methods.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.audit_events import enforce_audit_kwargs
from app.core.clock import utcnow

logger = logging.getLogger("aurion.audit")

# Terraform's ECS task definition ships the table name as
# DYNAMODB_AUDIT_TABLE (see infrastructure/ecs.tf). Old AUDIT_LOG_TABLE
# var name kept as fallback so a local shell with the legacy export
# still works. The "aurion-audit-log-local" default is the LocalStack
# table from backend/scripts/localstack-init/setup.sh — docker-compose only.
_TABLE_NAME = (
    os.getenv("DYNAMODB_AUDIT_TABLE")
    or os.getenv("AUDIT_LOG_TABLE")
    or "aurion-audit-log-local"
)
_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")


class AuditLogService:
    """Append-only DynamoDB audit log.

    There are intentionally no update() or delete() methods on this class.
    The audit log is immutable by design.
    """

    def __init__(self) -> None:
        kwargs: dict[str, Any] = {"region_name": _REGION}
        if _ENDPOINT_URL:
            kwargs["endpoint_url"] = _ENDPOINT_URL
        self._table = boto3.resource("dynamodb", **kwargs).Table(_TABLE_NAME)

    async def write_event(
        self,
        session_id: str | uuid.UUID,
        event_type: str,
        **extra_fields: Any,
    ) -> dict[str, Any]:
        """Write an immutable audit log entry.

        Args:
            session_id: The session this event belongs to.
            event_type: Event type string (e.g. 'consent_confirmed') or
                        an ``AuditEventType`` member.
            **extra_fields: Additional fields to include in the record.
                            Must not contain PHI. Validated against
                            ``ALLOWED_AUDIT_KWARGS`` (Q-03) — unknown
                            keys raise in strict mode, warn in prod.

        Returns:
            The written audit record.
        """
        enforce_audit_kwargs(event_type, extra_fields)
        timestamp = utcnow().isoformat(timespec="milliseconds")
        record = {
            "session_id": str(session_id),
            "event_timestamp": timestamp,
            "event_type": event_type,
            "event_id": str(uuid.uuid4()),
            **{k: _serialize(v) for k, v in extra_fields.items()},
        }

        try:
            self._table.put_item(Item=record)
            logger.info(
                "Audit event written: session=%s event=%s",
                str(session_id),
                event_type,
            )
        except (BotoCoreError, ClientError) as e:
            logger.error(
                "Failed to write audit event: session=%s event=%s error=%s",
                str(session_id),
                event_type,
                str(e),
            )
            raise

        return record

    async def get_session_events(
        self, session_id: str | uuid.UUID
    ) -> list[dict[str, Any]]:
        """Retrieve all audit events for a session, ordered by timestamp."""
        try:
            response = self._table.query(
                KeyConditionExpression="session_id = :sid",
                ExpressionAttributeValues={":sid": str(session_id)},
                ScanIndexForward=True,
            )
            return response.get("Items", [])
        except (BotoCoreError, ClientError) as e:
            logger.error(
                "Failed to query audit log: session=%s error=%s",
                str(session_id),
                str(e),
            )
            raise


def _serialize(value: Any) -> Any:
    """Serialize values for DynamoDB.

    DynamoDB rejects Python `float` (precision-unsafe) — they must be passed
    as `Decimal`. UUIDs and datetimes are stringified for portability.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    if isinstance(value, float):
        # Round-trip through str so floats like 0.5 don't pick up binary noise.
        return Decimal(str(value))
    return value


# ── Module-level singleton ─────────────────────────────────────────────────

_service: Optional[AuditLogService] = None


def get_audit_log_service() -> AuditLogService:
    global _service
    if _service is None:
        _service = AuditLogService()
    return _service
