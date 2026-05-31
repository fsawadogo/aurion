"""template_authoring_sessions table — conversational template builder

Phase 9a — backing store for the ChatGPT-style template authoring flow
in the clinician web portal. Each row tracks one in-progress (or
finalized) authoring conversation: the message history, the latest
LLM-emitted draft template JSON, and a status enum.

Resumable: the physician can close the tab and reopen from another
device — GET /me/template-authoring/{id} rehydrates from this table.

On finalize, the draft_template_json is validated against the Template
Pydantic schema and inserted as a custom_templates row owned by the
same clinician; the authoring row stays for audit but flips to
status=completed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-31
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_authoring_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        # JSON-encoded list of {"role": "user" | "assistant", "content": "..."}
        # objects. Bounded by an application-level message limit (default 40)
        # so a runaway conversation doesn't bloat the row indefinitely.
        sa.Column("messages_json", sa.Text(), nullable=False, server_default="[]"),
        # The latest LLM-emitted draft, JSON-encoded. null until the assistant
        # produces a valid Template-schema candidate. Replaced (not appended)
        # each time the LLM emits a new draft.
        sa.Column("draft_template_json", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "completed",
                "abandoned",
                name="template_authoring_status",
            ),
            nullable=False,
            server_default="active",
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
    )


def downgrade() -> None:
    op.drop_table("template_authoring_sessions")
    op.execute("DROP TYPE IF EXISTS template_authoring_status")
