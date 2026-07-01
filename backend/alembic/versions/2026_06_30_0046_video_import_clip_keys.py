"""video_import_jobs.raw_video_s3_keys — ordered multi-clip key list

Adds a nullable JSONB column holding the ordered list of clip S3 keys for a
multi-clip video import (sequential parts of one encounter, concatenated in
order into one audio timeline → one note). NULL for legacy / single-clip jobs,
which fall back to [raw_video_s3_key]. Additive + nullable → inert on add;
single-clip behaviour is unchanged. Gated in the UIs by
feature_flags.multi_clip_import_enabled.

Revision ID: 0046
Revises: 0045
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "video_import_jobs",
        sa.Column("raw_video_s3_keys", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("video_import_jobs", "raw_video_s3_keys")
