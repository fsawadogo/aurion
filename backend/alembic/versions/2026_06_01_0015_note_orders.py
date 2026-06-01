"""note_orders table — structured orders extracted from approved notes

#58 foundation. The clinical reality: a physician says "we'll get an
MRI of the left knee and refer to ortho" in the encounter, and the
note records that as free-text plan claims. This table captures the
same information as STRUCTURED rows the physician can confirm with
a single tap (vs re-typing into the EMR or writing on a pad).

Schema:
  id                       UUID primary key
  session_id               UUID indexed — the source session
  kind                     enum: imaging / lab / referral / prescription
  details                  JSONB — type-specific fields:
      imaging:   { modality, body_part, laterality, indication }
      lab:       { panel, indication }
      referral:  { specialty, reason, urgency }
      prescription: { drug, dose, frequency, duration, indication }
  status                   draft / confirmed / sent / cancelled
                           — extracted rows start as `draft`,
                             physician confirms before they're
                             eligible for outbound delivery (#57)
  source_claim_ids         JSONB array of claim IDs the row traces
                           back to (gives the audit story a citation
                           chain into the note)
  physician_confirmed_at   nullable timestamp; set when draft → confirmed
  sent_at                  nullable; set by future EMR write-back (#57)
  created_at, updated_at

The details column is PHI-adjacent (drug names, body parts) and stays
out of logs and out of audit rows.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "imaging",
                "lab",
                "referral",
                "prescription",
                name="note_order_kind",
            ),
            nullable=False,
        ),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "confirmed",
                "sent",
                "cancelled",
                name="note_order_status",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "source_claim_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "physician_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
    )


def downgrade() -> None:
    op.drop_table("note_orders")
    op.execute("DROP TYPE IF EXISTS note_order_status")
    op.execute("DROP TYPE IF EXISTS note_order_kind")
