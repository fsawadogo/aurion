"""Password hashing helpers — bcrypt with a 12-round cost factor.

bcrypt automatically generates and embeds the salt in the hash; verification
is constant-time. We never store, log, or transmit plaintext passwords.
"""

from __future__ import annotations

import bcrypt

_ROUNDS = 12


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash suitable for storage in users.password_hash."""
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    digest = bcrypt.hashpw(plaintext.encode("utf-8"), salt)
    return digest.decode("utf-8")


def verify_password(plaintext: str, password_hash: str) -> bool:
    """Constant-time check. Returns False if the hash is malformed."""
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
