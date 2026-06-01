"""physician_macros table — owner-scoped clinical phrase shortcuts

Phase 9b / #60 foundation. Each physician maintains a personal library
of shortcut → body mappings; typing the shortcut in a note edit field
expands to the body. Cuts the boilerplate-typing tax that drives the
clinician value prop of an AI scribe.

Schema:
  id          UUID primary key
  owner_id    UUID indexed — the physician this macro belongs to
  shortcut    short token typed by the physician (e.g. "/ros-cv")
  body        the expansion text (plain text only)
  specialty   optional — restricts the macro to one specialty's
              note generation; null = available across specialties
  is_shared   reserved for future community sharing; false today
  created_at, updated_at

Indexed unique on (owner_id, shortcut) so a single physician can't
collide their own shortcuts. Cross-owner collisions are fine —
"/ros" can mean different things to different physicians.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "physician_macros",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        # Shortcut is the trigger token; limited to a tight length so
        # an accidental paste of a paragraph into the shortcut field
        # doesn't blow up the row. Practical scheme is typically
        # `/two-or-three-words` — 64 chars is way more than needed.
        sa.Column("shortcut", sa.String(64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # Optional scope. Null = always available; specific = only
        # expanded inside that specialty's notes. The portal UI can
        # surface this as a dropdown when creating a macro.
        sa.Column("specialty", sa.String(50), nullable=True),
        sa.Column(
            "is_shared",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "owner_id", "shortcut", name="uq_physician_macros_owner_shortcut"
        ),
    )


def downgrade() -> None:
    op.drop_table("physician_macros")
