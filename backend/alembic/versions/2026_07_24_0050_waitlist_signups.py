"""waitlist_signups table — public marketing-site contact submissions.

The peritwin.com marketing site is a static export with no server; its
contact form posts to ``POST /api/v1/public/waitlist`` which inserts here.
Insert-only lead data (name/email PII — never logged), no PHI, no FK into
clinical tables.

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("specialty", sa.String(length=200), nullable=True),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default="website",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_waitlist_signups_created_at", "waitlist_signups", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_waitlist_signups_created_at", table_name="waitlist_signups")
    op.drop_table("waitlist_signups")
