"""Compliance reporting module (issue #77 foundation)."""

from app.modules.compliance.reports_service import (
    ComplianceReportsService,
    ReportType,
    get_compliance_reports_service,
)

__all__ = [
    "ComplianceReportsService",
    "ReportType",
    "get_compliance_reports_service",
]
