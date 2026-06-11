"""eval_scores provider attribution (#74 / OV-1).

Adds nullable provider_used + model_name to eval_scores and backfills
provider_used from each scored session's latest note version, so quality
scores join to providers without chasing the session→note chain at query
time. model_name stays NULL until per-call usage records carry it.

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_scores",
        sa.Column("provider_used", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "eval_scores",
        sa.Column("model_name", sa.String(length=128), nullable=True),
    )
    # Backfill from the latest note version per scored session. Pilot
    # scale (hundreds of rows) — a correlated UPDATE is fine.
    op.execute(
        """
        UPDATE eval_scores es
        SET provider_used = nv.provider_used
        FROM (
            SELECT DISTINCT ON (session_id) session_id, provider_used
            FROM note_versions
            ORDER BY session_id, version DESC
        ) nv
        WHERE nv.session_id = es.session_id
          AND es.provider_used IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("eval_scores", "model_name")
    op.drop_column("eval_scores", "provider_used")
