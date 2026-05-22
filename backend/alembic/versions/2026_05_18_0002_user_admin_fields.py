"""user admin fields

Adds three columns to ``users`` so admin endpoints can persist the
account-state fields they previously held in an in-memory dict
(``MOCK_USERS``): ``is_active``, ``voice_enrolled``, ``last_login_at``.

The defaults make this safe to apply to an existing pilot DB without
data migration: every existing row gets is_active=true,
voice_enrolled=false, last_login_at=NULL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "users",
        sa.Column(
            "voice_enrolled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Drop the server_defaults now that all existing rows are populated.
    # New rows get their defaults from the Python-side `default=` in the
    # ORM mapping; keeping server-side defaults would cause autogenerate
    # noise on every subsequent migration check.
    op.alter_column("users", "is_active", server_default=None)
    op.alter_column("users", "voice_enrolled", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "voice_enrolled")
    op.drop_column("users", "is_active")
