"""prompt_overrides — rename overlay_text → user_prompt_text
(AI-PROMPTS-B refactor to replacement semantics)

The Phase B v1 model treated the saved row as an *append-only overlay*
glued below the base prompt. The CTO clarified the model is
**replacement**: when a clinician saves a prompt it is sent to the LLM
*alone*; the registry's ``system_prompt`` is now a fallback used only
when no saved row exists.

The column name from v1 (``overlay_text``) misrepresents this. The
forward migration here renames it to ``user_prompt_text``. We do NOT
edit the original ``2026_06_03_0025_prompt_overrides.py`` migration —
that one already shipped through PR #227 v1 and any developer who ran
it has an ``overlay_text`` column. This migration takes them forward
in lockstep with the code rename.

The rename is reversible: ``downgrade`` undoes the column rename so a
developer on this branch can step back to revision 0025 cleanly.

Schema invariants unchanged:
  * UNIQUE (owner_id, prompt_id)
  * INDEX (owner_id)
  * NOT NULL on the renamed column

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename ``prompt_overrides.overlay_text`` → ``user_prompt_text``.

    Postgres ``ALTER TABLE ... RENAME COLUMN`` is metadata-only — no
    table rewrite, no data copy. Safe to run during a live deploy with
    a few overlay rows already in place; the rename is atomic.

    The associated index (``ix_prompt_overrides_owner``) doesn't
    reference the column name in its definition and survives the rename
    untouched.
    """
    op.alter_column(
        "prompt_overrides",
        "overlay_text",
        new_column_name="user_prompt_text",
    )


def downgrade() -> None:
    """Rename the column back to ``overlay_text`` so this revision is
    reversible."""
    op.alter_column(
        "prompt_overrides",
        "user_prompt_text",
        new_column_name="overlay_text",
    )
