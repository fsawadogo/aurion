"""user.prompt_testing_enabled — per-user prompt-testing capability (#590)

Adds an opt-in per-user boolean: when True the user may re-run note generation
on their OWN uploaded encounters with a different template/prompt
(POST /sessions/{id}/regenerate-note). Default False (server_default) so the
column is inert on add — enforcement is opt-in via the admin Users toggle.
Mirrors the mfa_required column add (migration 0039).

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "prompt_testing_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "prompt_testing_enabled")
