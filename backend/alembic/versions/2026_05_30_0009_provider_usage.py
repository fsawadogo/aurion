"""provider_usage table

Issue #73 — per-call AI-provider telemetry. Tokens/cost columns are
nullable until the base.py interface refactor surfaces them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_usage_provider_type", "provider_usage", ["provider_type"])
    op.create_index("ix_provider_usage_provider_name", "provider_usage", ["provider_name"])
    op.create_index("ix_provider_usage_session_id", "provider_usage", ["session_id"])
    op.create_index("ix_provider_usage_created_at", "provider_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_usage_created_at", table_name="provider_usage")
    op.drop_index("ix_provider_usage_session_id", table_name="provider_usage")
    op.drop_index("ix_provider_usage_provider_name", table_name="provider_usage")
    op.drop_index("ix_provider_usage_provider_type", table_name="provider_usage")
    op.drop_table("provider_usage")
