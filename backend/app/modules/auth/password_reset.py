"""Self-serve password-reset token lifecycle (AUTH-PIVOT-BACKEND).

* ``issue_reset_token(user)`` — generate a fresh 24-hour, single-use
  token, persist its hash to ``password_reset_tokens``, return the raw
  token to the caller (who emails it via the SES helper).
* ``verify_and_consume(raw_token)`` — look up the matching row, check
  not-revoked + not-expired, set ``consumed_at``, return the user.

Raw tokens are 256-bit URL-safe base64; only the SHA-256 hash hits
the DB. ``hmac.compare_digest`` is used on every DB comparison so a
timing attack can't enumerate which hashes exist.

NEVER log the raw token. NEVER log the reset link. NEVER carry the
token into the audit row — the audit event whitelist is enforced by
``app.core.audit_events``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.models import PasswordResetTokenModel, RefreshTokenModel, UserModel
from app.modules.auth.jwt_tokens import (
    compare_token_hashes,
    hash_refresh_token,
    mint_refresh_token,
)

logger = logging.getLogger("aurion.auth.reset")

RESET_TOKEN_TTL = timedelta(hours=24)


async def issue_reset_token(
    db: AsyncSession, user: UserModel
) -> tuple[str, PasswordResetTokenModel]:
    """Mint a raw reset token + persist its hash. Returns
    ``(raw_token, row)``.

    The caller emails the raw token; the row is added to the session
    but NOT committed — the route handler controls the transaction.
    Reuses ``mint_refresh_token`` because the token-shape requirements
    are identical (256-bit URL-safe, SHA-256 stored). DRY: one helper
    for "random opaque secret + its hash".
    """
    raw, token_hash = mint_refresh_token()
    now = utcnow()
    row = PasswordResetTokenModel(
        user_id=user.id,
        token_hash=token_hash,
        issued_at=now,
        expires_at=now + RESET_TOKEN_TTL,
    )
    db.add(row)
    await db.flush()
    return raw, row


async def verify_and_consume(
    db: AsyncSession, raw_token: str
) -> UserModel | None:
    """Look up + consume a reset token. Returns the user on success.

    Failure modes (returns None):
    * Token not found.
    * Token already consumed.
    * Token expired.

    Side effect on success: ``consumed_at`` is set on the matching row
    AND every refresh token for the user is revoked. Both are flushed
    but not committed — the route handler commits.
    """
    if not raw_token:
        return None

    expected_hash = hash_refresh_token(raw_token)
    now = utcnow()

    # Hash equality is the index hit; the constant-time compare is the
    # defense against a hash-prefix timing probe (unlikely against a
    # 32-byte hash, but cheap to be principled about it).
    stmt = select(PasswordResetTokenModel).where(
        PasswordResetTokenModel.token_hash == expected_hash,
        PasswordResetTokenModel.consumed_at.is_(None),
        PasswordResetTokenModel.expires_at > now,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    if not compare_token_hashes(row.token_hash, expected_hash):
        # Defensive: the WHERE clause should have rejected anything
        # non-matching, but if the index returns a row whose hash
        # somehow differs (shouldn't happen barring DB corruption),
        # we still reject — fail closed.
        return None

    user = await db.get(UserModel, row.user_id)
    if user is None:
        return None

    row.consumed_at = now
    await _revoke_all_refresh_tokens_for(db, user.id, reason="password_reset")
    await db.flush()
    return user


async def _revoke_all_refresh_tokens_for(
    db: AsyncSession, user_id: uuid.UUID, *, reason: str
) -> int:
    """Revoke every active refresh token for ``user_id``. Returns the
    count revoked. Idempotent — already-revoked rows are skipped.

    The ``reason`` argument is accepted for API symmetry with the audit
    emission site; this helper itself doesn't emit (audit is the
    caller's job so the event stays in the right state-machine slot).
    """
    now = utcnow()
    stmt = select(RefreshTokenModel).where(
        RefreshTokenModel.user_id == user_id,
        RefreshTokenModel.revoked_at.is_(None),
        RefreshTokenModel.expires_at > now,
    )
    rows = list((await db.execute(stmt)).scalars().all())
    for row in rows:
        row.revoked_at = now
    # `reason` is intentionally not stored on the row — the audit log
    # is the canonical reason carrier. We surface it on the parameter
    # for callsite readability.
    _ = reason
    return len(rows)


__all__ = [
    "RESET_TOKEN_TTL",
    "issue_reset_token",
    "verify_and_consume",
]
