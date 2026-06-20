"""video_import — web-portal encounter-video import foundation (VID-01).

Adds the ``video_import_jobs`` job table (mirrors ``stage2_jobs``) and an
additive nullable ``sessions.import_source`` provenance column. Ships inert:
nothing writes rows / sets the column until the video-import endpoints land
behind ``feature_flags.video_import_enabled``.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("import_source", sa.String(length=20), nullable=True),
    )
    op.create_table(
        "video_import_jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_video_s3_key", sa.Text(), nullable=True),
        sa.Column("raw_video_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "frames_extracted",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "frames_masked",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "frames_dropped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "auto_advance_stage2",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("new_note_version", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_video_import_jobs_session_id",
        "video_import_jobs",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_video_import_jobs_session_id",
        table_name="video_import_jobs",
    )
    op.drop_table("video_import_jobs")
    op.drop_column("sessions", "import_source")
