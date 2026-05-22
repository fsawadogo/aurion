"""eval scores

Creates the ``eval_scores`` table that replaces the in-memory
``_EVAL_SCORES`` dict in ``admin/eval.py``. One row per session;
re-scoring overwrites in place.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_scores",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("transcript_accuracy", sa.Float, nullable=False),
        sa.Column("citation_correctness", sa.Float, nullable=False),
        sa.Column("descriptive_mode_compliance", sa.Float, nullable=False),
        sa.Column("overall", sa.Float, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("scored_by", sa.String(255), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("eval_scores")
