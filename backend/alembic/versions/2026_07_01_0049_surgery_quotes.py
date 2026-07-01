"""surgery_quotes table — patient-facing surgical cost quote (note-Options ph.3)

One-to-many on session (regenerate/edit → new version; max-version row is what
the UI shows). ``line_items`` is a JSONB list of
``{id, procedure, description, fee_cents}`` — the LLM drafts the procedures
(grounded in the approved note, never a price) and the physician fills the
fees. Mirrors ``patient_summaries`` (#14): ownership flows through
``sessions.clinician_id``; (session_id, version) is unique.

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surgery_quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "line_items",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'CAD'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("generated_by_provider", sa.String(40), nullable=False),
        sa.Column(
            "physician_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.UniqueConstraint(
            "session_id", "version", name="uq_surgery_quotes_session_version"
        ),
    )


def downgrade() -> None:
    op.drop_table("surgery_quotes")
