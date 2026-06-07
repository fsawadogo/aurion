"""Session custom_template_id snapshot column

Issue #318 (B3) — phase 2 of Visit Type → Context → Template. A context
can bind a CUSTOM template (``template_ref``, a ``custom_templates`` row
owned by the clinician) instead of a built-in ``template_key``. When that
binding resolves at session create time, the owned custom-template id is
snapshotted onto the session so Stage 1 can load its content
deterministically.

Adds one nullable column to ``sessions``:

* ``custom_template_id`` — ``UUID``, the resolved-and-owned
  ``custom_templates`` id the chosen context's ``template_ref`` pointed
  at. Mutually exclusive with ``template_key`` in practice (a context
  binds one or the other). NULL means "no custom template" — use
  ``template_key`` or the session ``specialty`` default, byte-for-byte
  the pre-#318 behaviour. A plain UUID, NOT a DB-level FK: the
  custom_templates row may be deleted after snapshot, in which case
  Stage 1 degrades to the specialty default rather than failing a
  constraint.

Nullable with no server default so existing rows decode as NULL (the
built-in / specialty-default path) without a backfill.

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "custom_template_id",
            UUID(as_uuid=True),
            nullable=True,
            comment=(
                "Snapshot of the owned custom_templates id the chosen"
                " context's template_ref resolved to (#318 / B3). NULL ="
                " no custom template (use template_key or specialty"
                " default). Plain UUID, not an FK — the row may be deleted"
                " after snapshot; Stage 1 then degrades to the specialty"
                " default."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "custom_template_id")
