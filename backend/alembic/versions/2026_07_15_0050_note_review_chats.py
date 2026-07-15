"""note_review_chats table — per-session "Fix this note" conversation

One row per encounter session (session_id is the PK): the chat is scoped to
that session's note and resumable across devices. Messages may reference note
content, so the row is PHI-bearing like note_versions (Postgres, never
logged). Applied edits are NOT stored here — each one goes through
note_gen.create_note_version, keeping the note's immutable version history
the single source of truth. Gated by feature_flags.note_review_chat_enabled.

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-15
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
        "note_review_chats",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "messages_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("note_review_chats")
