"""coding_suggestions.code_validated — catalog validation flag (#69 follow-up)

Computed at extraction time by `modules/coding/catalog.validate_code()`.
Old rows default to NULL (unknown — they were extracted before
validation existed); the portal renders NULL as "not validated" with
a different visual treatment than False (which means "actively
checked and not in catalog").

The validation result is stored, not computed on read:
  * decouples the catalog from request latency
  * preserves the catalog state at extraction time (catalogs evolve;
    re-validating an old row could flip its flag and would confuse
    the audit story)

The catalog itself is curated (NOT the full ~70K-code ICD-10 set):
common ortho / plastic-surgery / family-medicine codes plus the
full E/M code family + common CPT procedure codes. False means "the
code wasn't in OUR catalog" — the UI surfaces this as caution-worthy
rather than as a hard error.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coding_suggestions",
        sa.Column("code_validated", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("coding_suggestions", "code_validated")
