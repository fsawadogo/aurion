"""Physician profile contexts_per_visit_type map

Issue #313 (B1) — profile schema foundation for the Visit Type →
Context → Template feature.

Adds one column to ``physician_profiles``:

* ``contexts_per_visit_type`` — a JSON object stored as text (same
  convention as the sibling ``consultation_types`` / ``preferred_templates``
  / ``allied_health_team`` columns). Keyed by visit-type key (a canonical
  default consultation type OR a custom clinician-authored label) → an
  ordered list of context objects ``{id, label, template_key,
  template_ref}``. ``template_key`` points at a built-in specialty
  template; ``template_ref`` (the custom-template pointer) is always null
  in phase 1.

NOT NULL with a ``'{}'`` server default so existing rows decode as an
empty map without a backfill.

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "physician_profiles",
        sa.Column(
            "contexts_per_visit_type",
            sa.Text(),
            nullable=False,
            server_default="{}",
            comment=(
                "JSON map (stored as text) of visit-type key → ordered list"
                " of context objects {id, label, template_key, template_ref}."
                " template_ref is always null in phase 1 (#313)."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("physician_profiles", "contexts_per_visit_type")
