"""grounded_lab_runs.run_type — discriminate grounded-lab vs fusion-compare jobs.

The async lab-run table now backs two job kinds: the descriptive-vs-grounded
caption replay ("grounded_lab") and the Fusion A vs Fusion B note comparison
("fusion_compare"). A run_type column lets the poll endpoints validate the
right result_json shape. Existing rows default to "grounded_lab".

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "grounded_lab_runs",
        sa.Column(
            "run_type",
            sa.String(length=30),
            nullable=False,
            server_default="grounded_lab",
        ),
    )


def downgrade() -> None:
    op.drop_column("grounded_lab_runs", "run_type")
