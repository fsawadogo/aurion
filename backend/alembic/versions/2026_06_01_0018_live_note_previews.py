"""live_note_previews table — streaming draft note snapshots during recording

#64 foundation. Beyond live captions — physician watches the note
assemble in near-real-time while still in the room with the patient.

Each row is one snapshot. We keep history rather than overwriting a
single "current preview" row because:
  * the audit trail benefits from knowing how the note evolved
  * pilot metrics may want to chart "preview quality at minute 1 vs
    minute 5 of an encounter"
  * cheap on storage (a few KB JSON per preview, max ~20 previews per
    session)

The previews are NOT the canonical Stage 1 note. The route guard +
the `stage=0` marker in the response make this explicit; the
canonical pipeline at recording-stop still runs the full Stage 1
generation independently. Foundation slice: previews live until the
session is purged.

Schema:
  id                 UUID PK
  session_id         UUID indexed
  version            Integer — sequential snapshot number within the
                     session, 1-indexed. Composite unique with
                     session_id so concurrent generations can't
                     collide.
  sections           JSONB — the Note.sections shape (status +
                     claims + ids). PHI-bound by definition; never
                     in logs / audit rows.
  transcript_chars   Integer — how many characters of transcript
                     were available when this preview was generated.
                     Useful for the "preview quality over time" chart.
  completeness_score Float — from the LLM
  provider_used      String(32) — which provider generated this
                     preview (for evaluation + cost telemetry)
  created_at         timestamp

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_note_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sections", postgresql.JSONB(), nullable=False),
        sa.Column("transcript_chars", sa.Integer(), nullable=False),
        sa.Column(
            "completeness_score", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column("provider_used", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "session_id", "version", name="uq_live_preview_session_version"
        ),
    )


def downgrade() -> None:
    op.drop_table("live_note_previews")
