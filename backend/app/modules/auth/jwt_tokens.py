"""Backend-issued JWT minting + verification (AUTH-PIVOT-BACKEND).

This module is the ONE source of truth for all access-token + refresh-
token issuance. No other module signs or verifies a JWT — every route
handler that needs to mint a token calls into here, and ``get_current_user``
calls into here to verify incoming Bearer tokens.

Design notes
------------
* **HS256, not RS256.** Aurion is a single backend issuing tokens for a
  single backend to verify. There's no third party in the trust chain;
  asymmetric signing would add key-rotation complexity without buying a
  threat-model improvement. The signing key sits in AWS Secrets Manager
  and is loaded into ``AUTH_JWT_SIGNING_KEY`` by the ECS task definition.

* **Refresh tokens are NOT JWTs.** They're 256-bit URL-safe base64
  strings — opaque, unparseable, single-purpose. The DB stores their
  SHA-256 hash so revocation is a constant-time index lookup. This is
  deliberate: JWT refresh tokens can't be reliably revoked without an
  out-of-band block list, and an opaque random secret is strictly
  simpler than maintaining one.

* **Access TTL 30 minutes / refresh TTL 30 days** — tuned for the iOS
  pilot. Short enough that a leaked access token is bounded; long
  enough that a clinician on a slow conference Wi-Fi doesn't get
  bumped mid-encounter.

* **Constant-time comparison.** ``hmac.compare_digest`` is used on the
  refresh-token-hash path so a timing attack can't enumerate which
  hashes exist in the DB. Bcrypt covers the password path.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from dataclasses import dataclass

from jose import JWTError, jwt

from app.core.clock import utcnow
from app.core.types import UserRole

logger = logging.getLogger("aurion.auth.jwt")

# ── Configuration ───────────────────────────────────────────────────────────
#
# Signing key is loaded at module import once and cached. We never log
# the key (even truncated). The fallback default is a process-only
# random key so an accidentally-undeployed prod task fails closed (the
# tokens it mints won't validate on the next pod), rather than picking
# up a predictable default that another instance could forge against.
_SIGNING_KEY = os.getenv("AUTH_JWT_SIGNING_KEY") or secrets.token_urlsafe(64)
_JWT_ALGORITHM = "HS256"
_JWT_ISSUER = os.getenv("AUTH_JWT_ISSUER", "aurion-backend")
_JWT_AUDIENCE = os.getenv("AUTH_JWT_AUDIENCE", "aurion-clients")

ACCESS_TOKEN_TTL_SECONDS = 30 * 60          # 30 minutes
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
MFA_CHALLENGE_TTL_SECONDS = 5 * 60          # 5 minutes


@dataclass(frozen=True, slots=True)
class AccessTokenPayload:
    """The verified decoded contents of an access token. No methods —
    callers pull fields directly. ``user_id`` is already a UUID.

    ``jti`` is a per-token UUID minted on issuance. It links the access
    token back to the refresh-token row it was minted from — the
    /me/sessions endpoint reads ``access_token_jti`` on each refresh row
    and flags ``is_current=True`` on the row whose JTI matches the
    bearer-token JTI of the caller. ``None`` for legacy access tokens
    minted before #163.
    """

    user_id: uuid.UUID
    role: UserRole
    email: str
    issued_at: int   # epoch seconds
    expires_at: int  # epoch seconds
    jti: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class MfaChallengePayload:
    """Decoded MFA challenge token contents. Single-use signal that the
    bearer has passed the password gate and may now present a TOTP code."""

    user_id: uuid.UUID
    email: str
    expires_at: int


# ── Access tokens ───────────────────────────────────────────────────────────


def mint_access_token(
    *,
    user_id: uuid.UUID,
    role: UserRole,
    email: str,
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
    jti: uuid.UUID | None = None,
) -> tuple[str, int, uuid.UUID]:
    """Mint a signed access token for ``user_id`` / ``role`` / ``email``.

    Returns ``(token, expires_in_seconds, jti)``. The JTI is a UUID
    minted here unless the caller supplies one — the caller persists
    it onto the refresh-token row so /me/sessions can flag the
    "current" session.
    """
    now = int(utcnow().timestamp())
    expires_at = now + ttl_seconds
    token_jti = jti or uuid.uuid4()
    claims = {
        "sub": str(user_id),
        "role": role.value,
        "email": email,
        "iat": now,
        "exp": expires_at,
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "type": "access",
        "jti": str(token_jti),
    }
    token = jwt.encode(claims, _SIGNING_KEY, algorithm=_JWT_ALGORITHM)
    return token, ttl_seconds, token_jti


def verify_access_token(token: str) -> AccessTokenPayload | None:
    """Verify a Bearer access token. Returns None on any failure
    (expired, signature invalid, wrong issuer, wrong audience, malformed).

    The caller raises 401 — we never raise from here so the failure
    path stays generic across attacker probes.
    """
    try:
        claims = jwt.decode(
            token,
            _SIGNING_KEY,
            algorithms=[_JWT_ALGORITHM],
            audience=_JWT_AUDIENCE,
            issuer=_JWT_ISSUER,
            options={"verify_at_hash": False},
        )
    except JWTError:
        return None

    if claims.get("type") != "access":
        return None

    try:
        user_id = uuid.UUID(claims["sub"])
        role = UserRole(claims["role"])
    except (KeyError, ValueError):
        return None

    jti_raw = claims.get("jti")
    try:
        jti = uuid.UUID(jti_raw) if jti_raw else None
    except (ValueError, TypeError):
        jti = None

    return AccessTokenPayload(
        user_id=user_id,
        role=role,
        email=claims.get("email", ""),
        issued_at=int(claims.get("iat", 0)),
        expires_at=int(claims.get("exp", 0)),
        jti=jti,
    )


# ── Refresh tokens ──────────────────────────────────────────────────────────


def mint_refresh_token() -> tuple[str, bytes]:
    """Mint a fresh refresh token. Returns ``(raw_token, sha256_hash)``.

    The raw token is what the client persists; the SHA-256 hash is what
    the DB persists. The two never appear side-by-side outside this
    function and the issuing route's `add()` call.
    """
    raw = secrets.token_urlsafe(32)  # 256 bits → ~43 chars
    token_hash = hash_refresh_token(raw)
    return raw, token_hash


def hash_refresh_token(raw: str) -> bytes:
    """SHA-256 of the raw token. Constant-time-safe with
    ``hmac.compare_digest`` at the equality check site."""
    return hashlib.sha256(raw.encode("utf-8")).digest()


def compare_token_hashes(left: bytes, right: bytes) -> bool:
    """Constant-time equality. Use this rather than ``==`` whenever an
    attacker-controlled hash is being compared to a DB-side hash."""
    return hmac.compare_digest(left, right)


# ── MFA challenge tokens ────────────────────────────────────────────────────
#
# These are short-lived JWTs that bridge the password gate and the TOTP
# verify call. They prove the bearer passed step 1; without one, step 2
# can't complete. We use a JWT here (not an opaque random) because the
# bridge is stateless — no DB row, no revocation needed; the 5-minute
# TTL is the only safety net, and a clock-bound JWT carries that
# cleanly.


def mint_mfa_challenge_token(*, user_id: uuid.UUID, email: str) -> str:
    """Mint a 5-minute MFA challenge token bound to ``user_id``."""
    now = int(utcnow().timestamp())
    claims = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + MFA_CHALLENGE_TTL_SECONDS,
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "type": "mfa_challenge",
    }
    return jwt.encode(claims, _SIGNING_KEY, algorithm=_JWT_ALGORITHM)


def verify_mfa_challenge_token(token: str) -> MfaChallengePayload | None:
    """Verify an MFA challenge token; None on any failure."""
    try:
        claims = jwt.decode(
            token,
            _SIGNING_KEY,
            algorithms=[_JWT_ALGORITHM],
            audience=_JWT_AUDIENCE,
            issuer=_JWT_ISSUER,
            options={"verify_at_hash": False},
        )
    except JWTError:
        return None

    if claims.get("type") != "mfa_challenge":
        return None

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError):
        return None

    return MfaChallengePayload(
        user_id=user_id,
        email=claims.get("email", ""),
        expires_at=int(claims.get("exp", 0)),
    )


# ── IP-hash helper for refresh-token forensics ──────────────────────────────


def hash_ip(raw_ip: str) -> bytes:
    """SHA-256 of an IP address for the refresh_tokens.issued_ip_hash
    column. One-way storage — a forensics query joins by computing
    the same hash, never by reversing the column."""
    if not raw_ip:
        return b""
    return hashlib.sha256(raw_ip.encode("utf-8")).digest()


# ── Test helper ─────────────────────────────────────────────────────────────


def _reset_signing_key_for_tests(key: str | None = None) -> None:
    """Test-only — swap the signing key without re-importing the module.

    Used by ``tests/integration/test_auth_*`` to set a deterministic key
    when assertions need to inspect tokens. NEVER call from production
    code; the module-level singleton is the security boundary.
    """
    global _SIGNING_KEY
    _SIGNING_KEY = key or secrets.token_urlsafe(64)


# Re-export so ``__all__`` is explicit and grep-friendly.
__all__ = [
    "AccessTokenPayload",
    "MfaChallengePayload",
    "ACCESS_TOKEN_TTL_SECONDS",
    "REFRESH_TOKEN_TTL_SECONDS",
    "MFA_CHALLENGE_TTL_SECONDS",
    "mint_access_token",
    "verify_access_token",
    "mint_refresh_token",
    "hash_refresh_token",
    "compare_token_hashes",
    "mint_mfa_challenge_token",
    "verify_mfa_challenge_token",
    "hash_ip",
]

