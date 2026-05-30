"""compliance_reports table

Issue #77 — persisted, hash-signed compliance report snapshots.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_type", sa.String(32), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_compliance_reports_report_type",
        "compliance_reports",
        ["report_type"],
    )
    op.create_index(
        "ix_compliance_reports_generated_at",
        "compliance_reports",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_reports_generated_at", table_name="compliance_reports")
    op.drop_index("ix_compliance_reports_report_type", table_name="compliance_reports")
    op.drop_table("compliance_reports")
