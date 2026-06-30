"""user_role: CLINICAL_ADMIN elevatable super-user value

lane-full/tpl-central-4-clinical-admin (#578).

Adds the ``CLINICAL_ADMIN`` value to the ``user_role`` PG enum. The Python enum
(``app/core/types.py``) and the elevatable admin endpoints (System Templates,
Shared Templates, Prompt Studio) reference it, and the Users admin endpoint can
assign it — but the value must exist in the database enum first or an INSERT /
UPDATE of a CLINICAL_ADMIN user hits ``invalid input value for enum user_role``.

PostgreSQL 12+ accepts ``ALTER TYPE ... ADD VALUE`` inside a transaction; the
new value is only referenced by application code on a fresh connection after
this migration commits, so the plain ``op.execute(...)`` path works for both
online migrations and the offline SQL renderer the test suite exercises.
IF NOT EXISTS keeps it idempotent against a dev DB seeded from the updated
baseline list in 2026_05_14_0001_initial_schema.py.

The downgrade is a no-op: PostgreSQL enums have no ``DROP VALUE`` and the
workaround (recreate the type without the value) would orphan any user rows
assigned the new role.

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'CLINICAL_ADMIN'")


def downgrade() -> None:
    # PostgreSQL has no ``ALTER TYPE ... DROP VALUE``. Removing this value would
    # require recreating the enum type without it, orphaning any users assigned
    # the role. The honest downgrade is a no-op (see migration 0043's rationale).
    pass
