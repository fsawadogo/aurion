"""physician_profiles: portal UI preferences (Phase A1)

Two new columns on physician_profiles for the web portal's UI prefs:

  ui_theme       — "system" | "light" | "dark" (default "system")
  ui_language    — "en" | "fr" (default "en") for the portal chrome

`ui_language` is intentionally distinct from the existing
`output_language` column:
  * output_language = the language the LLM generates the clinical
    note in — physician's note-output preference
  * ui_language = the language of the portal/iOS chrome itself
    (sidebar labels, button text, etc.)

A physician might dictate in English but read the chrome in French
(or vice versa) — they're orthogonal.

Both nullable with defaults so legacy rows survive without backfill.
Capped at 16 chars to leave room for IETF language tags like "fr-CA"
without bloating the column.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "physician_profiles",
        sa.Column("ui_theme", sa.String(length=16), nullable=False,
                  server_default="system"),
    )
    op.add_column(
        "physician_profiles",
        sa.Column("ui_language", sa.String(length=16), nullable=False,
                  server_default="en"),
    )


def downgrade() -> None:
    op.drop_column("physician_profiles", "ui_language")
    op.drop_column("physician_profiles", "ui_theme")
