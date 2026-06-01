"""coding_suggestions table — E/M, ICD-10, CPT physician-confirmed billing

#69 foundation — strategic separate surface.

Aurion's clinical note is descriptive-only by policy (no inference, no
diagnosis, no recommendation). Coding/billing is fundamentally
inferential — you map free-text observations to a discrete code.
Resolving the contradiction: the suggestions live in their OWN table,
get rendered on their OWN portal card explicitly labeled "Assistive —
physician must confirm," and NEVER write back into the clinical note's
sections or claims.

Schema:
  id                        UUID PK
  session_id                UUID indexed — source session
  code_system               em / icd10 / cpt
  code                      the literal code string (e.g. "99213",
                            "M25.561", "73721") — VARCHAR(32). No
                            normalization here; that's the EMR's job
                            on write-back.
  description               human-readable label as the LLM emitted
                            it (e.g. "Office/outpatient visit, est
                            patient, low MDM") — Text. May be edited
                            by the physician.
  justification             free-text reason the LLM picked this code,
                            anchored back to claims via source_claim_ids
                            — Text. The audit story.
  source_claim_ids          JSONB array of claim IDs the row traces
                            back to. Same citation chain as #58.
  confidence                low / medium / high — LLM's self-rating.
                            UI biases reviewer attention toward low.
  status                    suggested / confirmed / rejected / edited.
                            * suggested: LLM emitted, untouched
                            * confirmed: physician accepted as-is
                            * rejected: physician rejected (row stays
                              for audit, doesn't go to EMR)
                            * edited:   physician changed code or
                              description; treated as confirmed for
                              outbound but flagged for the audit
                              trail that the LLM's pick was overridden
  physician_action_at       nullable; set on confirm/reject/edit
  created_at, updated_at

The `description`, `justification`, and any inferential text are
PHI-adjacent — patient body parts, findings, etc. They stay out of
logs and the audit log. Audit rows carry `code_system` + `code` +
`actor_id` + transition only.

The `code` itself is NOT PHI (it's a billing code), but the mapping
of a specific patient session → a specific code IS PHI when joined
with patient identity, which is why the row lives under session_id
ownership scope just like everything else.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coding_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "code_system",
            sa.Enum("em", "icd10", "cpt", name="coding_system"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "source_claim_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "confidence",
            sa.Enum("low", "medium", "high", name="coding_confidence"),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "suggested",
                "confirmed",
                "rejected",
                "edited",
                name="coding_status",
            ),
            nullable=False,
            server_default="suggested",
        ),
        sa.Column(
            "physician_action_at",
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
    op.drop_table("coding_suggestions")
    op.execute("DROP TYPE IF EXISTS coding_status")
    op.execute("DROP TYPE IF EXISTS coding_confidence")
    op.execute("DROP TYPE IF EXISTS coding_system")
