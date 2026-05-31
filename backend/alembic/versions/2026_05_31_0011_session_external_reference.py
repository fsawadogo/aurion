"""sessions: encrypted external_reference_id (patient identifier)

Phase 9a — adds an optional, KMS-encrypted patient identifier on the
session (MRN hash, EMR encounter ID, etc.). Forward-compatible with
FHIR DocumentReference.identifier for the future EMR write-back path
(#57) without a later schema migration.

Single column: ciphertext blob from KMS.encrypt (no separate IV needed
at this payload size — MRN-style identifiers fit comfortably under the
4 KB KMS-direct limit). Reading the row alone never yields PHI;
decryption requires KMS Decrypt permission (IAM-gated in prod,
LocalStack KMS in dev).

The column-level PHI tag is captured in the model docstring + audit
policy rather than as a DDL constraint Postgres can't enforce.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-31
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("external_reference_id_encrypted", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "external_reference_id_encrypted")
