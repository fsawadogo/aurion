"""org_visit_type_templates — org-wide default template per visit type

Adds the org-level visit-type -> template default map. Two-tier mapping: this
org default sits between a clinician's own visit-type default (a visit type's
is_default context, #577) and the specialty default inside
resolve_context_template_key. One row per visit-type key; single-org (no org_id)
for the pilot. template_key XOR custom_template_id is enforced at the API layer.
Additive -> inert until an admin sets a row (byte-identical resolution otherwise).

Revision ID: 0047
Revises: 0046
Create Date: 2026-06-30
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
        "org_visit_type_templates",
        sa.Column("visit_type", sa.String(length=100), primary_key=True),
        sa.Column("template_key", sa.String(length=50), nullable=True),
        sa.Column(
            "custom_template_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("org_visit_type_templates")
