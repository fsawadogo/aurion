"""Alerts module — operational alert publisher/list (issue #76)."""

from app.modules.alerts.service import (
    AlertService,
    AlertSeverity,
    get_alert_service,
)

__all__ = ["AlertSeverity", "AlertService", "get_alert_service"]
