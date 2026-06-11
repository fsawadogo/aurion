"""user.mfa_required — MFA enforcement mechanism (#397 / OV-5).

Per-user flag: when True the user must enroll TOTP before a password
login completes. Default False (server_default) so the column is inert on
add — enforcement is opt-in via the admin toggle; the global policy is a
CTO decision, not a migration.

Revision ID: 0037
Revises: 0036
"""

import sqlalchemy as sa

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_required")
