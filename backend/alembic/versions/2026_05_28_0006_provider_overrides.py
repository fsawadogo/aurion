"""provider overrides

Creates the ``provider_overrides`` table for the global runtime
AI-provider override layer. One row per provider type
("transcription" | "note_generation" | "vision") — the registry's
in-memory cache is refreshed from this table every ~10s, so an
ADMIN/COMPLIANCE_OFFICER can pin the active provider at runtime
without a redeploy.

The audit log preserves the full history; this table holds only the
current effective override (upsert in place, delete to clear).

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_overrides",
        sa.Column("provider_type", sa.String(32), primary_key=True),
        sa.Column("provider_value", sa.String(32), nullable=False),
        sa.Column("set_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_overrides")
