"""template_overrides table

Issue #72 — admin CRUD over specialty templates. Storage layer only;
runtime integration (cache + poller) lands in a follow-up PR.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_overrides",
        sa.Column("template_key", sa.String(64), primary_key=True),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("template_overrides")
