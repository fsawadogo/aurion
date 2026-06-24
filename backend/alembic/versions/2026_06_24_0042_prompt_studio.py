"""prompt_studio — admin prompt authoring / versioning / rollout (PS-01).

Adds the three tables backing the Prompt Studio:
  * ``studio_prompts``          — named admin candidate per AI job.
  * ``studio_prompt_versions``  — append-only versions of a candidate.
  * ``prompt_publications``     — append-only rollout (self / role / all).

Ships inert: nothing writes rows until the Studio API + publish land
(ps-03 / ps-05) behind ``feature_flags.prompt_studio_enabled``. Separate from
``prompt_overrides`` (per-clinician replacement) by design.

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_prompts",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_studio_prompts_job_id", "studio_prompts", ["job_id"])

    op.create_table(
        "studio_prompt_versions",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "studio_prompt_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("studio_prompts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "studio_prompt_id",
            "version_no",
            name="uq_studio_prompt_versions_prompt_version",
        ),
    )
    op.create_index(
        "ix_studio_prompt_versions_studio_prompt_id",
        "studio_prompt_versions",
        ["studio_prompt_id"],
    )

    op.create_table(
        "prompt_publications",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column(
            "version_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("studio_prompt_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("target_role", sa.String(length=24), nullable=True),
        sa.Column(
            "target_user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_prompt_publications_job_id", "prompt_publications", ["job_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_publications_job_id", table_name="prompt_publications"
    )
    op.drop_table("prompt_publications")
    op.drop_index(
        "ix_studio_prompt_versions_studio_prompt_id",
        table_name="studio_prompt_versions",
    )
    op.drop_table("studio_prompt_versions")
    op.drop_index("ix_studio_prompts_job_id", table_name="studio_prompts")
    op.drop_table("studio_prompts")
