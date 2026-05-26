"""eval scores spec-aligned

Adds 4 nullable columns to ``eval_scores`` so the eval team can record
the richer per-spec quality breakdown alongside the legacy three-slider
shape. New columns are nullable so already-scored sessions stay valid
and clients that haven't been updated can keep submitting the legacy
payload without sending the new fields.

New columns:
  - descriptive_mode_pass:  bool   — pass / fail per spec
  - soap_section_scores:    jsonb  — {section_id: int 0..5} per spec
  - hallucination_count:    int    — claims not traceable to any source
  - discrepancies:          jsonb  — free-form list[str] of flagged issues

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_scores",
        sa.Column("descriptive_mode_pass", sa.Boolean, nullable=True),
    )
    op.add_column(
        "eval_scores",
        sa.Column("soap_section_scores", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "eval_scores",
        sa.Column("hallucination_count", sa.Integer, nullable=True),
    )
    op.add_column(
        "eval_scores",
        sa.Column("discrepancies", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_scores", "discrepancies")
    op.drop_column("eval_scores", "hallucination_count")
    op.drop_column("eval_scores", "soap_section_scores")
    op.drop_column("eval_scores", "descriptive_mode_pass")
