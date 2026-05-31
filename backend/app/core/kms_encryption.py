"""KMS-backed string encryption for PHI columns.

Aurion stores small PHI strings (patient identifiers / MRN hashes / EMR
encounter IDs) on `sessions.external_reference_id_encrypted`. Reading the
raw row never yields plaintext: decryption requires AWS KMS Decrypt
permission, gated by IAM in prod and the LocalStack KMS endpoint in dev.

Direct KMS encrypt/decrypt (rather than envelope encryption with a data
key) because these payloads are small — well under KMS's 4 KB direct-
encrypt limit — and we get a single self-contained ciphertext blob with
no IV management. If we ever store larger PHI per row this module is
the right place to evolve to envelope encryption.

Configuration:
  AWS_DEFAULT_REGION — region for the KMS client (default ca-central-1)
  AWS_ENDPOINT_URL   — LocalStack endpoint in dev; absent in prod
  KMS_KEY_ID         — key alias or ARN to use (default alias/aurion-phi)

`encrypt_str(plaintext) -> bytes` and `decrypt_str(ciphertext) -> str`
are intentionally synchronous: callers run them inside the existing
async-route bodies where a single ≤10 ms KMS RPC won't hurt the event
loop, and a thread-pool wrapper would obscure simpler code. If the
profile changes (bulk encrypt of N rows) wrap in `asyncio.to_thread`.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

REGION: str = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
ENDPOINT_URL: str | None = os.getenv("AWS_ENDPOINT_URL")
KMS_KEY_ID: str = os.getenv("KMS_KEY_ID", "alias/aurion-phi")

_kms_client: Any | None = None


def get_kms_client() -> Any:
    """Cached boto3 KMS client.

    Mirrors `app.core.s3.get_s3_client` — same region resolution, same
    LocalStack endpoint override. Boto3 clients are thread-safe so a
    module-level singleton is fine.
    """
    global _kms_client
    if _kms_client is None:
        kwargs: dict[str, Any] = {"region_name": REGION}
        if ENDPOINT_URL:
            kwargs["endpoint_url"] = ENDPOINT_URL
        _kms_client = boto3.client("kms", **kwargs)
    return _kms_client


def encrypt_str(plaintext: str, key_id: str | None = None) -> bytes:
    """Encrypt a small string with KMS. Returns the opaque ciphertext blob.

    Empty / None input is a programming error (we never want to encrypt
    nothing and store noise); the caller should NULL the column instead
    of calling encrypt_str("").
    """
    if not plaintext:
        raise ValueError(
            "encrypt_str called with empty string — set the column to NULL "
            "rather than encrypting nothing"
        )
    response = get_kms_client().encrypt(
        KeyId=key_id or KMS_KEY_ID,
        Plaintext=plaintext.encode("utf-8"),
    )
    return response["CiphertextBlob"]


def decrypt_str(ciphertext: bytes) -> str:
    """Decrypt a ciphertext blob produced by encrypt_str. Returns the plaintext."""
    if not ciphertext:
        raise ValueError("decrypt_str called with empty ciphertext")
    response = get_kms_client().decrypt(CiphertextBlob=ciphertext)
    return response["Plaintext"].decode("utf-8")


def reset_client_for_tests() -> None:
    """Drop the cached client. Test helper — production code never calls this."""
    global _kms_client
    _kms_client = None
