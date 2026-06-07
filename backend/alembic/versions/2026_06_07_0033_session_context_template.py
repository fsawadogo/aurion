"""Session context_id + template_key snapshot columns

Issue #314 (B2) — carry the chosen Visit Type → Context → Template
selection onto the session so Stage 1 generates against the resolved
template.

Adds two nullable columns to ``sessions``:

* ``context_id`` — ``String(40)``, the ``ctx_<8hex>`` id of the context
  the clinician chose at create time (from B1's ``contexts_per_visit_type``
  map, #313). NULL when none chosen or the client predates the feature.
* ``template_key`` — ``String(64)``, the SNAPSHOT of the built-in
  specialty template that context resolved to (validated against
  ``list_available_templates`` at create time). NULL means "use the
  session ``specialty`` default" — byte-for-byte the pre-#314 behaviour.

Both nullable with no server default so existing rows decode as NULL
(specialty-default path) without a backfill.

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "context_id",
            sa.String(length=40),
            nullable=True,
            comment=(
                "ctx_<8hex> id of the context chosen at session create"
                " (B1 contexts_per_visit_type, #313). NULL = none chosen."
            ),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "template_key",
            sa.String(length=64),
            nullable=True,
            comment=(
                "Snapshot of the built-in template the chosen context"
                " resolved to (#314). NULL = use the session specialty"
                " default (pre-#314 behaviour)."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "template_key")
    op.drop_column("sessions", "context_id")
