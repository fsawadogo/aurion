"""refresh_tokens + password_reset_tokens

AUTH-PIVOT-BACKEND, slice 2/2.

Creates two new tables that back the backend-issued JWT auth path.
``refresh_tokens`` holds the rotating opaque secret that lets the iOS
+ web clients refresh their short-lived access tokens; the raw value
is returned exactly once in the issuing response body and the DB
holds only ``token_hash`` (SHA-256). ``password_reset_tokens`` holds
the single-use email-link reset secret with the same hashed storage.

Both tables FK to ``users.id`` with ``ON DELETE CASCADE`` so the
existing admin delete-user path (and any future user-deactivation
follow-ups) sweeps every credential a user holds in one transaction.

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_user_agent", sa.String(255), nullable=True),
        sa.Column("issued_ip_hash", sa.LargeBinary(), nullable=True),
    )
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"]
    )
    op.create_index(
        "ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"]
    )
    op.create_index(
        "ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"]
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_token_hash",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_user_id",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
    op.drop_index(
        "ix_refresh_tokens_expires_at", table_name="refresh_tokens"
    )
    op.drop_index(
        "ix_refresh_tokens_token_hash", table_name="refresh_tokens"
    )
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
