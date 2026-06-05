"""session_state: STAGE1_FAILED_NO_AUDIO terminal value

lane-backend/empty-transcript-guard.

Adds the ``STAGE1_FAILED_NO_AUDIO`` value to the ``session_state`` PG enum
so Stage 1 can transition a session into a terminal failure state when
the transcript is empty / missing / below the AppConfig char threshold
WITHOUT calling the note-generation provider. Calling an LLM with zero
source material invites hallucination — CLAUDE.md §"The Single Most
Important Constraint" forbids it.

PostgreSQL enum values can only be added with ``ALTER TYPE ... ADD VALUE``
which can't run inside a transaction; ``op.execute(...)`` is wrapped in
the standard ``COMMIT; ALTER TYPE ...; BEGIN;`` pattern alembic uses on
``postgresql_immutable=True`` enums. We use the simpler isolation_level
escape hatch via ``op.get_bind().execution_options(...)`` so the migration
plays cleanly on both the dev DB and CI postgres.

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
    # ALTER TYPE ... ADD VALUE must run outside a transaction block in
    # PostgreSQL. Alembic wraps every migration in BEGIN/COMMIT by default,
    # so we hop to AUTOCOMMIT for this single DDL.
    bind = op.get_bind()
    bind = bind.execution_options(isolation_level="AUTOCOMMIT")
    bind.exec_driver_sql(
        "ALTER TYPE session_state ADD VALUE IF NOT EXISTS 'STAGE1_FAILED_NO_AUDIO'"
    )


def downgrade() -> None:
    # PostgreSQL has no ``ALTER TYPE ... DROP VALUE``. Removing this
    # value would require recreating the enum type without it, which
    # orphans any rows already in the new state. The honest downgrade
    # is a no-op + a row migration in a follow-up. See the module
    # docstring for the longer-form rationale.
    pass
