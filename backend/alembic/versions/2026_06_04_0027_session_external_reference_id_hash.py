"""sessions: external_reference_id_hash (indexed HMAC for lookup)

#61 — Longitudinal Patient Context (Full Slice).

Adds a deterministic HMAC-SHA256 column alongside the existing
KMS-encrypted ``external_reference_id_encrypted`` so the per-physician
prior-encounters lookup (and the new ``get_prior_context`` call in
Stage 1 note generation) hits an indexed equality predicate instead of
scanning + decrypting every session row.

Why a second column rather than indexing the ciphertext directly?
  KMS direct-encrypt embeds a fresh IV inside every CiphertextBlob —
  two encrypts of the same plaintext produce different blobs by
  construction, so the ciphertext column can't be the lookup key. The
  hash column is deterministic (same plaintext → same digest) and is
  one-way (HMAC; an attacker who scrapes a DB backup of this column
  alone can't reverse the patient identifier without the HMAC key,
  which lives in Secrets Manager).

Schema:
  - external_reference_id_hash  LargeBinary  NULL
    32 raw bytes when set; NULL when the session has no identifier.
  - ix_sessions_external_reference_id_hash  B-tree on the new column.

Data migration:
  Every existing row with a non-NULL ``external_reference_id_encrypted``
  gets its hash computed and back-filled in the same migration. Pilot
  scale (~hundreds of sessions) makes the in-place pass trivial; for
  larger scales the same logic could move to a separate offline job.

  The back-fill calls into ``app.core.kms_encryption.decrypt_str`` and
  ``app.core.identifier_hash.hash_identifier``. KMS Decrypt permissions
  must be available at migration time (they already are for any env
  the API runs in). A row whose ciphertext fails to decrypt is logged
  + skipped — leaving its hash NULL means it falls out of the indexed
  lookup, which is the right failure mode (better to miss one row in
  the rail than to crash every Stage 1 generation behind it).

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-04
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.0027")


def upgrade() -> None:
    """Add the column + index, then back-fill existing rows.

    The DDL part (add_column + create_index) is fast metadata-only on
    Postgres for a NULL column. The data migration is a per-row UPDATE
    via the active SQL connection — keeps every transaction inside the
    Alembic upgrade so a failure mid-migration rolls the schema back
    cleanly.
    """
    op.add_column(
        "sessions",
        sa.Column(
            "external_reference_id_hash", sa.LargeBinary(), nullable=True
        ),
    )
    op.create_index(
        "ix_sessions_external_reference_id_hash",
        "sessions",
        ["external_reference_id_hash"],
    )

    # Offline mode (``alembic upgrade --sql``) renders the upgrade as
    # static SQL and the bind doesn't return rows. Back-fill is a no-
    # op there; the operator runs the script against a live DB instead.
    if op.get_context().as_sql:
        logger.info(
            "Skipping #61 back-fill in offline SQL mode — run "
            "scripts/backfill_identifier_hash.py against the live DB."
        )
        return

    # Back-fill — decrypt every existing ciphertext and write its hash.
    # Imports are inside the function so a `downgrade` shell that
    # doesn't have the FastAPI app's import path still works (Alembic
    # imports the migration module on `downgrade` too).
    try:
        from app.core.identifier_hash import hash_identifier
        from app.core.kms_encryption import decrypt_str
    except ImportError as exc:
        # Running outside the app context — the back-fill is a no-op,
        # which leaves the columns NULL. Lookup falls back to "no
        # match" for those rows (acceptable; covered above).
        logger.warning(
            "Skipping #61 back-fill: app modules not importable (%s). "
            "Run scripts/backfill_identifier_hash.py against the live "
            "DB instead.", exc,
        )
        return

    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT id, external_reference_id_encrypted "
            "FROM sessions "
            "WHERE external_reference_id_encrypted IS NOT NULL "
            "AND external_reference_id_hash IS NULL"
        )
    )
    # Defensive — some test harnesses stub the bind so `execute`
    # returns None; treat that the same as offline mode.
    if result is None:
        logger.warning(
            "Skipping #61 back-fill — bind.execute returned no result."
        )
        return
    rows = result.fetchall()

    for row in rows:
        try:
            plaintext = decrypt_str(bytes(row[1]))
        except Exception as exc:  # noqa: BLE001 — KMS errors logged + skipped
            logger.warning(
                "Backfill skipped session=%s (decrypt failed): %s",
                row[0], exc,
            )
            continue
        digest = hash_identifier(plaintext)
        bind.execute(
            sa.text(
                "UPDATE sessions SET external_reference_id_hash = :h "
                "WHERE id = :sid"
            ),
            {"h": digest, "sid": row[0]},
        )


def downgrade() -> None:
    """Drop the index + column. Reversible — the hash column is
    derived from the (still-present) encrypted column, so no data is
    lost on downgrade; a future upgrade re-runs the back-fill."""
    op.drop_index(
        "ix_sessions_external_reference_id_hash", table_name="sessions"
    )
    op.drop_column("sessions", "external_reference_id_hash")
