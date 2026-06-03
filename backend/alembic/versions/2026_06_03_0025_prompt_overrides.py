"""prompt_overrides — per-physician append-only LLM prompt overlays
(AI-PROMPTS-B)

Adds the storage backing for Phase B of the AI Prompts Transparency
feature: a small per-physician table that lets Marie or Perry append
preferences below an AI system prompt without modifying the descriptive-
mode base. The base text is unchanged at runtime; the overlay is joined
below a clear separator at assembly time.

Schema:
  - id           UUID PK
  - owner_id     UUID FK → users(id), cascade on delete
  - prompt_id    VARCHAR(64) — matches the PROMPTS dict key in
                 ``app.modules.prompts.registry``. NOT a FK (the
                 registry is in code, not the DB; new prompts ship with
                 the next deploy).
  - overlay_text TEXT — the physician's appended preferences. Bounded
                 to 1000 chars at the API layer (``modules/prompts/
                 safety.py``); no DB CHECK constraint because length
                 caps are policy that may evolve faster than schema.
  - created_at / updated_at  — standard timestamps with NOW() default.
  - UNIQUE (owner_id, prompt_id) — one overlay per (physician, prompt).
    Re-saving the same pair upserts; never collides.
  - INDEX (owner_id) — every read is filtered by owner, so this is the
    only hot index path. ``prompt_id`` is small (under 30 values today)
    so the composite isn't worth its write cost.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``prompt_overrides`` table.

    ``gen_random_uuid()`` is the same generator used by every existing
    UUID PK in the schema; ships with the ``pgcrypto`` extension which
    is already enabled by the initial migration.
    """
    op.create_table(
        "prompt_overrides",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt_id", sa.String(64), nullable=False),
        sa.Column("overlay_text", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "owner_id", "prompt_id", name="uq_prompt_overrides_owner_prompt"
        ),
    )
    op.create_index(
        "ix_prompt_overrides_owner",
        "prompt_overrides",
        ["owner_id"],
    )


def downgrade() -> None:
    """Drop the table + index. Reversible."""
    op.drop_index("ix_prompt_overrides_owner", table_name="prompt_overrides")
    op.drop_table("prompt_overrides")
