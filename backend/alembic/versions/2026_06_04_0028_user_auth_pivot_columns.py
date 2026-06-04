"""user table: auth-pivot columns (MFA + lockout + password change tracking)

AUTH-PIVOT-BACKEND, slice 1/2.

Adds five columns to ``users`` to support the backend-issued JWT auth
path that replaces Cognito:

* ``mfa_secret_encrypted``      KMS-encrypted TOTP base32 secret.
* ``mfa_enrolled_at``           Wall-clock when MFA was enrolled. Cheap
                                short-circuit for "MFA on?" without a
                                KMS Decrypt on every login.
* ``failed_login_count``        Per-user lockout counter. Reset on
                                successful login.
* ``locked_until``              Lockout expiry; NULL when not locked.
* ``last_password_changed_at``  Data anchor for the iOS forced-change
                                follow-up. Not enforced here.

All five columns are NULL/zero for existing rows; the defaults make
the migration safe on a populated dev DB without a data migration.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_secret_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "last_password_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Drop the server_default once all existing rows are populated. The
    # ORM ``default=0`` handles new rows; keeping a server_default would
    # cause autogenerate noise on every subsequent migration check.
    op.alter_column("users", "failed_login_count", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "last_password_changed_at")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "mfa_enrolled_at")
    op.drop_column("users", "mfa_secret_encrypted")
