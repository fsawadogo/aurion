"""corrections — in-app physician note corrections (correction memory).

Every in-app edit to a generated note is logged here (before/after text +
section + claim) when ``correction_memory_enabled`` is on, so the system can
later classify each correction and distil per-physician rules. Owner-scoped;
before/after text is note content (same PHI boundary as note_versions).

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corrections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("clinician_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=False),
        sa.Column("claim_id", sa.String(length=128), nullable=False),
        sa.Column("before_text", sa.Text(), nullable=False),
        sa.Column("after_text", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=True),
        sa.Column("note_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_corrections_clinician_id", "corrections", ["clinician_id"])


def downgrade() -> None:
    op.drop_index("ix_corrections_clinician_id", table_name="corrections")
    op.drop_table("corrections")
