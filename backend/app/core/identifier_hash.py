"""Deterministic HMAC hashing for patient identifiers.

Aurion stores patient identifiers KMS-encrypted on
``sessions.external_reference_id_encrypted`` (see ``kms_encryption.py``).
The ciphertext is opaque — every encrypt of the same plaintext produces
different bytes because KMS embeds a random IV. That's the right shape
for at-rest privacy: reading the row alone never tells you which patient
it is.

But it makes lookups expensive. The #61 foundation slice's
``GET /me/patients/{identifier}/sessions`` scanned the whole sessions
table for the calling clinician and called ``decrypt_str`` on every
encrypted row. Fine at pilot scale (~10 sessions per physician), but it
won't survive past the first hundred encounters per physician — and the
new ``get_prior_context`` call runs on every Stage 1 note-gen.

This module gives us a **deterministic** mapping from plaintext to a
32-byte hash that can be:

  * stored in a B-tree-indexed column (``sessions.external_reference_id_hash``)
  * compared with a single equality predicate
  * never decoded back into the identifier (HMAC is one-way)

HMAC-SHA256 (not plain SHA256) so an attacker who scrapes the
``external_reference_id_hash`` column from a database backup CANNOT
brute-force the original identifiers with a precomputed rainbow table
of common MRN formats — they'd need the HMAC key to match anything.

Key sourcing
-----------
The HMAC key lives in Secrets Manager at
``aurion/${env}/identifier-hmac-key`` (provisioned by
``infrastructure/secrets.tf``). The key is fetched once on first call
and cached for the process lifetime. For local development and tests
the env var ``AURION_IDENTIFIER_HMAC_KEY`` short-circuits the AWS call;
this is the same pattern the rest of the secret-consuming modules use.

Rotating the key is a breaking change for the indexed lookup (every
hash in the DB becomes incomparable until backfilled). Production
rotation will need a dual-write window; that's deferred until a future
PR — for the pilot, one stable key is enough.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import threading
from typing import Optional

import boto3

logger = logging.getLogger("aurion.identifier_hash")

# Same region resolution pattern as ``kms_encryption.py`` and
# ``s3.py`` — env-driven so LocalStack works in dev without
# special-casing.
_REGION: str = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_ENDPOINT_URL: Optional[str] = os.getenv("AWS_ENDPOINT_URL")
_SECRET_NAME: str = os.getenv(
    "AURION_IDENTIFIER_HMAC_SECRET_NAME",
    f"aurion/{os.getenv('AURION_ENV', os.getenv('APP_ENV', 'dev'))}/identifier-hmac-key",
)
_ENV_KEY_OVERRIDE = "AURION_IDENTIFIER_HMAC_KEY"

_cached_key: Optional[bytes] = None
_cache_lock = threading.Lock()


def _decode_key_material(raw: str) -> bytes:
    """Accept the secret as base64 or raw UTF-8.

    Terraform's initial secret value is the literal placeholder string
    until an operator rotates a real key in via the AWS CLI. The real
    key is 32 random bytes, typically base64-encoded for transport
    (``openssl rand -base64 32``). We try base64 first; on failure we
    fall back to the raw bytes so a stub value like
    ``"test-key-do-not-use"`` still works in dev/test.
    """
    try:
        decoded = base64.b64decode(raw, validate=True)
        # An accidental short base64 string (e.g. "abcd==") decodes to
        # under 16 bytes — treat as raw to avoid silently using a
        # too-short key. 32 bytes is the AES-256 length our policy
        # mandates for the HMAC key.
        if len(decoded) >= 16:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    return raw.encode("utf-8")


def _fetch_key_from_secrets_manager() -> bytes:
    """Pull the HMAC key from Secrets Manager.

    Returns the raw bytes after best-effort base64 decode. Boto3
    failures propagate — there's no useful fallback at the call site;
    a missing key is a deployment misconfiguration that must surface
    loudly.
    """
    kwargs: dict[str, object] = {"region_name": _REGION}
    if _ENDPOINT_URL:
        kwargs["endpoint_url"] = _ENDPOINT_URL
    client = boto3.client("secretsmanager", **kwargs)
    response = client.get_secret_value(SecretId=_SECRET_NAME)
    secret_string = response.get("SecretString") or ""
    return _decode_key_material(secret_string)


def _get_key() -> bytes:
    """Return the cached HMAC key, fetching on first use.

    Thread-safe — concurrent first-callers can race into the fetch,
    but the lock guarantees only one boto3 call happens. The cache
    survives for the process lifetime; key rotation requires a
    process restart (acceptable for the pilot).
    """
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    with _cache_lock:
        if _cached_key is not None:
            return _cached_key
        # Env override is the fast path for tests + local dev. We
        # check this first so a test never needs to mock Secrets
        # Manager just to call ``hash_identifier``.
        env_value = os.environ.get(_ENV_KEY_OVERRIDE)
        if env_value:
            _cached_key = _decode_key_material(env_value)
            return _cached_key
        _cached_key = _fetch_key_from_secrets_manager()
        return _cached_key


def hash_identifier(plaintext: str) -> bytes:
    """Hash a plaintext patient identifier with HMAC-SHA256.

    The output is the 32 raw bytes of the HMAC digest — the column
    type on ``sessions.external_reference_id_hash`` is ``LargeBinary``
    so the index is over the raw byte string.

    Empty input is a programming error (empty / whitespace identifiers
    must be NULLed at the call site before they reach this function);
    raising rather than silently returning a fixed digest avoids the
    "every empty session hashes to the same bytes and matches each
    other" trap.
    """
    if not plaintext:
        raise ValueError(
            "hash_identifier called with empty plaintext — NULL the "
            "column at the call site instead"
        )
    key = _get_key()
    return hmac.new(key, plaintext.encode("utf-8"), hashlib.sha256).digest()


def reset_cache_for_tests() -> None:
    """Drop the cached HMAC key. Test helper — production never calls this."""
    global _cached_key
    with _cache_lock:
        _cached_key = None
