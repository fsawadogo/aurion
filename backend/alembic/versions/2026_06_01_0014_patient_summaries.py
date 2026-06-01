"""patient_summaries table — plain-language after-visit summary per session

#59 foundation. Each row is one LLM-generated patient-facing summary
derived from an approved note. The schema accepts versioning so the
physician can regenerate or edit; the latest row (max `version` for
the session) is what the UI displays.

Schema:
  id              UUID primary key
  session_id      UUID indexed — the session this summary belongs to
  version         int (1, 2, … increments on regenerate / edit)
  body            generated text (PHI; stored as plain text on the
                  encrypted-at-rest RDS volume — no extra column-
                  level encryption needed)
  generated_by_provider
                  the LLM that produced it (anthropic/openai/gemini)
                  so the audit story stays clean
  physician_edited
                  bool — true when the row was authored / modified
                  by the physician's edit modal (vs raw LLM output)
  created_at, updated_at

We don't carry an `owner_id` separately — ownership flows through
`sessions.clinician_id` (the read path always joins to verify
ownership). Avoids drift if a session is ever reassigned.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "generated_by_provider", sa.String(40), nullable=False
        ),
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
            "session_id", "version", name="uq_patient_summaries_session_version"
        ),
    )


def downgrade() -> None:
    op.drop_table("patient_summaries")
