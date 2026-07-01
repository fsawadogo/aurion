"""schedule_entries table — per-clinician patient schedule

Issue #603 (last MVP scope item). Each clinician queues patients onto a
personal schedule: who they plan to see, an optional slot time, an
optional short note, and a lifecycle status. Owner-scoped like macros —
every query filters on ``clinician_id``. Not a calendar/booking system.

PHI posture mirrors ``sessions``: the patient identifier is stored
KMS-encrypted (``patient_identifier_encrypted``) plus a deterministic
HMAC (``patient_identifier_hash``, indexed) for lookup. Plaintext never
lands in a column, log, or audit row.

Schema:
  id                             UUID primary key
  clinician_id                   UUID indexed — owner scope
  patient_identifier_encrypted   bytea — KMS ciphertext (never plaintext)
  patient_identifier_hash        bytea indexed — HMAC-SHA256 for lookup
  status                         scheduled | in_progress | completed | cancelled
  scheduled_for                  optional slot time (no calendar logic)
  note                           optional short free-text (never audited)
  created_at, updated_at

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_entries",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "clinician_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        # PHI — KMS ciphertext + one-way HMAC, same pair as `sessions`.
        sa.Column(
            "patient_identifier_encrypted", sa.LargeBinary(), nullable=False
        ),
        sa.Column(
            "patient_identifier_hash",
            sa.LargeBinary(),
            nullable=False,
            index=True,
        ),
        # Lifecycle status — plain string, validated + transition-gated in
        # the service layer (mirrors `specialty` on physician_macros rather
        # than introducing a native PG enum type).
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'scheduled'"),
        ),
        sa.Column(
            "scheduled_for", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("note", sa.Text(), nullable=True),
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
    )


def downgrade() -> None:
    op.drop_table("schedule_entries")
