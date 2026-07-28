"""sessions.detail_level — per-session verbosity override (TE-1b).

TE-1 (#672) made the Stage-1 capture directive graded (brief / standard /
detailed) with resolution session-override → template → default, but shipped
no session override storage. This adds it: a nullable string column the
regenerate endpoint persists so a chosen level sticks across re-runs (same
write-back contract as the template pin and encounter_context).

Revision ID: 0051
Revises: 0050
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("detail_level", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "detail_level")
