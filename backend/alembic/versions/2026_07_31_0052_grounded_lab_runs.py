"""grounded_lab_runs — async descriptive-vs-grounded lab replay jobs.

The Grounded Lab re-captions a session's frames/clips twice (descriptive +
grounded). For a large frame set that runs past the 60s ALB idle timeout, so
the run is async: a row is created ``running``, a detached task writes the
paired result JSON, and the poll endpoint reads it. Mirrors
``video_import_jobs``' poll/recover shape. READ-ONLY — no note mutation.

Revision ID: 0052
Revises: 0051
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grounded_lab_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_json", JSONB, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_grounded_lab_runs_session_id", "grounded_lab_runs", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_grounded_lab_runs_session_id", table_name="grounded_lab_runs")
    op.drop_table("grounded_lab_runs")
