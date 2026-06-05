"""session_state: STAGE1_FAILED_NO_AUDIO terminal value

lane-backend/empty-transcript-guard.

Adds the ``STAGE1_FAILED_NO_AUDIO`` value to the ``session_state`` PG enum
so Stage 1 can transition a session into a terminal failure state when
the transcript is empty / missing / below the AppConfig char threshold
WITHOUT calling the note-generation provider. Calling an LLM with zero
source material invites hallucination — CLAUDE.md §"The Single Most
Important Constraint" forbids it.

PostgreSQL 12+ accepts ``ALTER TYPE ... ADD VALUE`` inside a transaction
block; the only caveat is that the new value can't be referenced in the
same transaction. We don't reference it here — application code first
sees the value on a fresh connection after the migration commits — so
the plain ``op.execute(...)`` path works for both online migrations and
the offline SQL renderer the test suite exercises.

The downgrade is a no-op: PostgreSQL enums have no ``DROP VALUE`` and the
defensive workaround (recreate the type without the value) would orphan
any session rows that landed in the new state. If we ever need to remove
it, the rollback is a row migration to a different state first.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-05
"""

from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``op.execute`` works in both online (real connection) and offline
    # (SQL render to stdout) modes — the latter is what
    # tests/integration/test_migrations.py exercises without a database.
    # IF NOT EXISTS keeps the migration idempotent against an enum that
    # already carries the value (e.g. a dev DB seeded from the updated
    # baseline list in 2026_05_14_0001_initial_schema.py).
    op.execute(
        "ALTER TYPE session_state ADD VALUE IF NOT EXISTS 'STAGE1_FAILED_NO_AUDIO'"
    )


def downgrade() -> None:
    # PostgreSQL has no ``ALTER TYPE ... DROP VALUE``. Removing this
    # value would require recreating the enum type without it, which
    # orphans any rows already in the new state. The honest downgrade
    # is a no-op + a row migration in a follow-up. See the module
    # docstring for the longer-form rationale.
    pass
