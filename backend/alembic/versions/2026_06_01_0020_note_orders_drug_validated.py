"""note_orders.drug_validated — drug catalog flag for prescription orders (#58 follow-up)

Computed at extraction time by `modules/orders/drug_catalog.validate_drug()`.
Mirrors `coding_suggestions.code_validated` from #69 — three-state
(True / False / None) where None means "the row predates validation".

Validation applies ONLY to `kind=prescription` rows. Imaging / lab /
referral orders don't have a drug field; the column stays NULL for
those forever. Per-kind enforcement happens in the service layer,
not via a CHECK constraint — keeping the schema flexible if a future
kind grows a drug component.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "note_orders",
        sa.Column("drug_validated", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("note_orders", "drug_validated")
