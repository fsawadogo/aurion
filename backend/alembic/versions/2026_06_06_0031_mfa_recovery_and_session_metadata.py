"""MFA recovery codes + refresh-token session metadata

Issue #163 — Portal MFA setup + active sessions on
`/portal/profile/account`.

Two related concerns ship in one migration because the portal
Security card touches both:

1. **MFA recovery codes + last-verified timestamp.** The auth-pivot
   PR (#234) shipped TOTP enrollment with only the encrypted secret
   and the `mfa_enrolled_at` flag. The portal MFA card needs:
   * A way for the clinician to recover access when their
     authenticator app is gone — 8 single-use recovery codes,
     bcrypt-hashed at rest, plaintext returned exactly once at
     enrollment.
   * A "last verified" timestamp on the card header so the
     clinician sees their MFA is actively in use.

2. **Per-session refresh-token metadata.** The portal's "Active
   sessions" card needs a human-readable label per session and a
   way to tell which row corresponds to the current browser. Three
   columns:
   * ``device_hint`` — derived UA fingerprint (e.g. ``"Safari · macOS"``),
     capped at 64 chars. Never the raw User-Agent. Plaintext because
     it is not PHI and is the only signal a clinician has when
     deciding which session to revoke.
   * ``last_used_at`` — updated on every successful refresh-token
     rotation so the card can sort by recency.
   * ``access_token_jti`` — the JTI of the most recent access
     token minted from this refresh row. Lets `GET /me/sessions`
     flag `is_current=True` on the row whose JTI matches the
     bearer token the caller used. Updated atomically with
     ``last_used_at``.

All new columns nullable so existing rows survive the migration
without backfill.

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-06
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "mfa_recovery_codes_hashed",
            JSONB(),
            nullable=True,
            comment=(
                "List of bcrypt hashes of one-time MFA recovery codes."
                " Plaintext codes never persisted; returned ONCE at"
                " enrollment."
            ),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "mfa_last_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Timestamp of the last successful TOTP verification."
                " Surfaced on the portal MFA card so the clinician sees"
                " their authenticator is actively in use."
            ),
        ),
    )

    # ── refresh_tokens ─────────────────────────────────────────────────
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "device_hint",
            sa.String(length=64),
            nullable=True,
            comment=(
                "Derived UA fingerprint (browser family + platform"
                " family). Never the raw User-Agent."
            ),
        ),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Set on /auth/refresh — drives the portal sessions card"
                " sort and the 'is_current' resolver."
            ),
        ),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "access_token_jti",
            UUID(as_uuid=True),
            nullable=True,
            comment=(
                "JTI of the most recent access token minted from this"
                " refresh row. Lets /me/sessions flag is_current."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "access_token_jti")
    op.drop_column("refresh_tokens", "last_used_at")
    op.drop_column("refresh_tokens", "device_hint")
    op.drop_column("users", "mfa_last_verified_at")
    op.drop_column("users", "mfa_recovery_codes_hashed")
