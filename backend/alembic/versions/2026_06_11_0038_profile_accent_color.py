"""physician_profiles.accent_color — personalization (#418 / OV-7).

Curated-palette accent key (default "gold" = brand default), the backend
foundation for per-physician accent theming. Default-"gold" so the column
is inert on add — visible theming arrives with the portal picker + token
wiring (the reviewed frontend slice).

Revision ID: 0038
Revises: 0036
"""

import sqlalchemy as sa

from alembic import op

revision = "0038"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "physician_profiles",
        sa.Column(
            "accent_color",
            sa.String(length=16),
            nullable=False,
            server_default="gold",
        ),
    )


def downgrade() -> None:
    op.drop_column("physician_profiles", "accent_color")
