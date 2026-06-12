"""measurement_citations — on-device visual measurement persistence (#63).

Stores physician-confirmed wound L/W + ROM measurements (numbers +
provenance only; never raw frames). Derived PHI: a session child row,
hard-deleted with the session. Ships dark — the feature is gated by
feature_flags.measurement_enabled, so the table is inert on add.

Revision ID: 0040
Revises: 0039
"""

import sqlalchemy as sa

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "measurement_citations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("measurement_id", sa.String(length=64), nullable=False),
        sa.Column("frame_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=8), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column(
            "confidence_reason",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("scale_source", sa.String(length=32), nullable=True),
        sa.Column(
            "masking_status",
            sa.String(length=16),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column(
            "physician_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "provider_used",
            sa.String(length=32),
            nullable=False,
            server_default="on_device",
        ),
        sa.Column(
            "model_version",
            sa.String(length=32),
            nullable=False,
            server_default="meas-1.0",
        ),
        sa.Column(
            "certified_measurement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "session_id", "measurement_id", name="uq_measurement_session_mid"
        ),
    )
    op.create_index(
        "ix_measurement_citations_session_id",
        "measurement_citations",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_citations_session_id",
        table_name="measurement_citations",
    )
    op.drop_table("measurement_citations")
