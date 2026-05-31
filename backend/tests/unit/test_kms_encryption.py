"""KMS encryption helper roundtrip + edge cases.

Uses a stubbed boto3 KMS client so the test runs without LocalStack.
The real KMS RPC is exercised by the integration suite (under
``backend/tests/integration/`` with LocalStack up). These unit tests
prove the helper's contracts: refuse empty input, surface ciphertext
unchanged on roundtrip, hit the configured KeyId.
"""

from __future__ import annotations

import pytest

from app.core import kms_encryption


class _StubKMSClient:
    """Minimal in-memory KMS stand-in. encrypt returns a deterministic
    blob keyed off the plaintext; decrypt reverses it. No real crypto —
    we're testing the wrapper's call shape, not the cipher."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def encrypt(self, **kwargs: object) -> dict[str, bytes]:
        self.calls.append(("encrypt", dict(kwargs)))
        plaintext = kwargs["Plaintext"]
        assert isinstance(plaintext, bytes)
        # Reversible "ciphertext": prepend a tag so we can verify the
        # decrypt path strips it. Real KMS blobs are opaque; this is
        # purely a unit-test crutch.
        return {"CiphertextBlob": b"ENC::" + plaintext}

    def decrypt(self, **kwargs: object) -> dict[str, bytes]:
        self.calls.append(("decrypt", dict(kwargs)))
        blob = kwargs["CiphertextBlob"]
        assert isinstance(blob, bytes)
        assert blob.startswith(b"ENC::"), "stub only accepts blobs it produced"
        return {"Plaintext": blob[5:]}


@pytest.fixture
def stub_kms(monkeypatch: pytest.MonkeyPatch) -> _StubKMSClient:
    stub = _StubKMSClient()
    kms_encryption.reset_client_for_tests()
    monkeypatch.setattr(kms_encryption, "get_kms_client", lambda: stub)
    return stub


def test_roundtrip_recovers_plaintext(stub_kms: _StubKMSClient) -> None:
    """encrypt_str → decrypt_str returns the original UTF-8 string."""
    plaintext = "MRN_TEST_001"

    ciphertext = kms_encryption.encrypt_str(plaintext)
    assert ciphertext != plaintext.encode("utf-8")  # actually opaque
    assert kms_encryption.decrypt_str(ciphertext) == plaintext


def test_roundtrip_preserves_unicode(stub_kms: _StubKMSClient) -> None:
    """Non-ASCII identifiers (accents, etc.) survive encode/decode."""
    plaintext = "Patient-Référence-Ω-001"

    ciphertext = kms_encryption.encrypt_str(plaintext)
    assert kms_encryption.decrypt_str(ciphertext) == plaintext


def test_empty_string_refused(stub_kms: _StubKMSClient) -> None:
    """Callers must NULL the column rather than encrypt empty input —
    encrypting noise produces a non-empty ciphertext that looks like a
    populated PHI value, which is the wrong on-disk state."""
    with pytest.raises(ValueError, match="empty string"):
        kms_encryption.encrypt_str("")


def test_empty_ciphertext_refused(stub_kms: _StubKMSClient) -> None:
    with pytest.raises(ValueError, match="empty ciphertext"):
        kms_encryption.decrypt_str(b"")


def test_uses_configured_key_id_by_default(stub_kms: _StubKMSClient) -> None:
    """encrypt_str sends KMS_KEY_ID (or the default alias) when no
    override is passed. Sets us up for per-environment key rotation
    later without changing call sites."""
    kms_encryption.encrypt_str("TEST")

    assert stub_kms.calls[0][0] == "encrypt"
    assert stub_kms.calls[0][1]["KeyId"] == kms_encryption.KMS_KEY_ID


def test_override_key_id_for_per_call_routing(stub_kms: _StubKMSClient) -> None:
    """Allows callers to encrypt under a different key without mutating
    the module-level config (useful for dual-key rotation windows)."""
    custom = "alias/aurion-phi-rotated"
    kms_encryption.encrypt_str("TEST", key_id=custom)

    assert stub_kms.calls[0][1]["KeyId"] == custom
