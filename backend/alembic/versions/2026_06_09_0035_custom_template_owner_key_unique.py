"""Unique (owner_id, key) on custom_templates

Custom-template hardening follow-up. The service layer checks per-owner key
uniqueness in-app (friendly 409), but without a DB constraint the
finalize/create paths could still race two rows with the same (owner_id, key)
— and a later ``scalar_one_or_none`` lookup then 500s with
``MultipleResultsFound``. This adds the real guarantee.

upgrade():
  1. Defensive dedup — delete any pre-existing duplicate (owner_id, key)
     rows, keeping the most-recently-updated one per group (ties broken by
     physical row id). Dev currently has zero custom_templates rows, so this
     is a no-op there; it's belt-and-suspenders in case rows land before the
     migration runs.
  2. Add the UNIQUE constraint uq_custom_templates_owner_key on
     (owner_id, key).

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Dedup: per (owner_id, key) keep the latest updated_at (ctid tiebreak),
    #    delete the rest, so the unique constraint can be added cleanly.
    op.execute(
        """
        DELETE FROM custom_templates a
        USING custom_templates b
        WHERE a.owner_id = b.owner_id
          AND a.key = b.key
          AND (
            a.updated_at < b.updated_at
            OR (a.updated_at = b.updated_at AND a.ctid < b.ctid)
          )
        """
    )
    # 2. Enforce one custom template per (owner, runtime key).
    op.create_unique_constraint(
        "uq_custom_templates_owner_key",
        "custom_templates",
        ["owner_id", "key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_custom_templates_owner_key", "custom_templates", type_="unique"
    )
