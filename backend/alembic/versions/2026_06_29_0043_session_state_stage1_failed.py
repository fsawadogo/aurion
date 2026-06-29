"""session_state: STAGE1_FAILED terminal value

lane-backend/stage1-failed-enum.

Adds the ``STAGE1_FAILED`` value to the ``session_state`` PG enum. The Python
enum (``app/core/types.py``) and the generic Stage-1-failure path
(``app/api/v1/transcription.py`` → ``transition_session(..., STAGE1_FAILED)``)
already use it, but the value was never added to the database enum — only
``STAGE1_FAILED_NO_AUDIO`` was (migration 0030). So when the note-generation
provider call fails (e.g. a truncated/unparseable Gemini response), the
failure handler's ``UPDATE sessions SET state='STAGE1_FAILED'`` hits
``invalid input value for enum session_state`` → the transaction is poisoned →
``mark_failed`` then also fails and the session/job is stranded.

PostgreSQL 12+ accepts ``ALTER TYPE ... ADD VALUE`` inside a transaction; the
new value is only referenced by application code on a fresh connection after
this migration commits, so the plain ``op.execute(...)`` path works for both
online migrations and the offline SQL renderer the test suite exercises.

The downgrade is a no-op: PostgreSQL enums have no ``DROP VALUE`` and the
workaround (recreate the type without the value) would orphan any session rows
that landed in the new state.

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``op.execute`` works in both online (real connection) and offline
    # (SQL render) modes. IF NOT EXISTS keeps it idempotent against an enum
    # already carrying the value (e.g. a dev DB seeded from the updated
    # baseline list in 2026_05_14_0001_initial_schema.py).
    op.execute("ALTER TYPE session_state ADD VALUE IF NOT EXISTS 'STAGE1_FAILED'")


def downgrade() -> None:
    # PostgreSQL has no ``ALTER TYPE ... DROP VALUE``. Removing this value would
    # require recreating the enum type without it, which orphans any rows already
    # in the new state. The honest downgrade is a no-op + a row migration in a
    # follow-up (see migration 0030's rationale).
    pass
