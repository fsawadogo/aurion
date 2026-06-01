"""emr_write_backs table — outbound delivery of approved notes to EMRs

#57 foundation. The single biggest competitive gap: DOCX/PDF export
doesn't get the note into the EMR. This table tracks every attempt
to push an approved note to an EMR via a pluggable connector.

Schema:
  id                        UUID PK
  session_id                UUID indexed — source session
  connector                 String(32) — connector key (e.g. "stub",
                            "fhir_generic", "oscar", "epic_smart").
                            Maps to the EMR connector registry. Stored
                            as a string (not enum) so adding a new
                            connector doesn't require a migration.
  status                    enum:
                              queued — created, not yet attempted
                              sending — connector run in progress
                              sent — connector returned success
                              failed — connector returned an error
                                       (retryable or terminal — see
                                        `error_reason`)
  external_id               nullable String(128) — the EMR's response
                            id (DocumentReference.id in FHIR; an HL7
                            ACK id otherwise). The audit link to the
                            other side of the wire.
  payload_fingerprint       String(64) — sha256 hex of the serialized
                            payload. Lets us detect "same note, same
                            connector, different result" without
                            storing the payload itself.
  error_reason              nullable Text — connector error message
                            on failure. Connector should sanitize
                            before returning (no PHI leakage).
  attempt_count             Integer — number of times we've tried
                            (including the current one). Bumped by
                            the service before each attempt.
  scheduled_at              nullable timestamp — when a retry should
                            fire. Null for terminal states.
  sent_at                   nullable timestamp — set on success.
  created_at, updated_at

The payload itself is NOT stored — payloads are PHI-bound and the
EMR is the source of truth post-send. Storing them would create a
second permanent copy of the note we'd have to manage.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emr_write_backs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("connector", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "sending",
                "sent",
                "failed",
                name="emr_write_back_status",
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "scheduled_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
    op.drop_table("emr_write_backs")
    op.execute("DROP TYPE IF EXISTS emr_write_back_status")
