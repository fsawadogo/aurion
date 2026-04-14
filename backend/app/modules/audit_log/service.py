"""DynamoDB audit log — append-only, no update or delete. Ever.

Every session state transition, AI call, config change, and data lifecycle
event is written here. The write interface intentionally has no update or
delete methods.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("aurion.audit")

_TABLE_NAME = os.getenv("AUDIT_LOG_TABLE", "aurion-audit-log-local")
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
            event_type: Event type string (e.g. 'consent_confirmed').
            **extra_fields: Additional fields to include in the record.
                            Must not contain PHI.

        Returns:
            The written audit record.
        """
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
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
    """Serialize values for DynamoDB — convert UUIDs and datetimes to strings."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    return value


# ── Module-level singleton ─────────────────────────────────────────────────

_service: Optional[AuditLogService] = None


def get_audit_log_service() -> AuditLogService:
    global _service
    if _service is None:
        _service = AuditLogService()
    return _service
