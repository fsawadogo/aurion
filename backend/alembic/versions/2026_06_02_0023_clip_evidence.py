"""frames table — dual-mode visual evidence (P1-1)

Creates the `frames` SQL table that backs the dual-mode visual evidence
plan (see docs/plans/p1-1-clip-evidence-schema.md). Today the backend
stores frame metadata only in S3 keys (frames/{session_id}/{ts}.jpg) and
captions live in memory during Stage 2 processing. P1-3 introduces the
new `POST /api/v1/clips/{session_id}` endpoint and the Stage 2 dispatch
that routes by evidence kind — both need a persisted row per piece of
visual evidence so the reviewer can filter, paginate, and tap-through.

The table is dual-mode from day one. `evidence_kind` defaults to
`'frame'` so any future backfill of existing-session frame metadata
slots in as the implicit kind without a data migration. Clips get
`evidence_kind='clip'` and carry `duration_ms` for the encoded window.

Schema:
  id                UUID primary key
  session_id        UUID FK -> sessions(id), indexed
  s3_key            text, the KMS-encrypted object key
  timestamp_ms      int, the trigger anchor in transcript time
  evidence_kind     varchar(8) NOT NULL DEFAULT 'frame' — 'frame' | 'clip'
  duration_ms       int NULL — populated for clips, null for frames
  created_at        timestamptz NOT NULL DEFAULT now()

Index on (session_id, evidence_kind) for the reviewer's filtered queries
("show me only the clips in this session" / "show me only the frames").

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frames",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False),
        # `evidence_kind` defaults to 'frame' so existing frame metadata
        # backfilled later slots in as the implicit kind without a data
        # migration. New clip rows must set 'clip' explicitly.
        sa.Column(
            "evidence_kind",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'frame'"),
        ),
        # Clip window in ms; null for frames.
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Reviewer filters by (session, evidence_kind) — "show me just the
    # clips for this session" and similar. Composite index covers both.
    op.create_index(
        "ix_frames_session_evidence_kind",
        "frames",
        ["session_id", "evidence_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_frames_session_evidence_kind", table_name="frames")
    op.drop_table("frames")
