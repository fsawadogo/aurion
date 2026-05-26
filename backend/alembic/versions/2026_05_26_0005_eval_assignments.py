"""eval assignments

Creates the ``eval_assignments`` table for per-session eval-team
assignments. One row per session — re-assigning overwrites in place.
``completed_at`` is set when the assignee submits a score.

The assignee_email + assigned_by_email columns are denormalized
copies of the user emails at assignment time. Storing them on the row
lets the GET endpoints render the email without an extra join, and
preserves the assignment history even if a user is later renamed or
deactivated.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_assignments",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assignee_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("assignee_email", sa.String(255), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_email", sa.String(255), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_eval_assignments_assignee",
        "eval_assignments",
        ["assignee_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_assignments_assignee", table_name="eval_assignments")
    op.drop_table("eval_assignments")
