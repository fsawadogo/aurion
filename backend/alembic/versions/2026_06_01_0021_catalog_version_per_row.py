"""catalog_version per-row on coding_suggestions + note_orders (#58 + #69 follow-up)

Catalogs ship in code and bump versions over time. Without storing
the catalog version on each row, an audit query that finds
`code_validated=False` or `drug_validated=False` can't reconstruct
the catalog state at extraction time — the answer depends on when
the row was extracted vs when the catalog was last revised.

Pre-existing rows have catalog_version=NULL (correct: they predate
this column). Going forward:
  * extraction populates it from the catalog module's
    get_catalog_version()
  * physician edits re-validate AND re-version (the override is now
    against the current catalog, not whatever was in effect at
    original extraction)
  * empty/zero-row catalogs deliberately set NULL (no validation
    happened) — see drug_validated NULL semantics for non-prescription
    order kinds

The column is short String(32) — the catalog version string format
is "<YYYY-MM-DD>.<n>" so it fits comfortably; we cap at 32 chars to
catch accidental misuse (no one should be putting a long string here).

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coding_suggestions",
        sa.Column("catalog_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "note_orders",
        sa.Column("catalog_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("note_orders", "catalog_version")
    op.drop_column("coding_suggestions", "catalog_version")
