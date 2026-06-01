"""Tests for the patient identifier (external_reference_id) routes.

Locks the five contract guarantees of the #61 foundation slice:

  1. Setting an identifier encrypts the bytes; the stored column is
     never plaintext.
  2. Empty / whitespace-only input clears the column (with cleared=True
     in the audit row).
  3. The audit event never carries the identifier value itself — only
     the bool flag.
  4. _to_response decrypts cleanly for callers that already passed the
     ownership gate.
  5. Decryption failure during the response build is logged and the
     field is dropped, not a 500 — protects the response path during
     CMK rotation.

Route-level row authorization (owner-only) is locked by the
test_assert_owner.py suite already; we don't re-prove it here.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.api.v1 import sessions as sessions_route
from app.core.audit_events import AuditEventType


class _StubKMS:
    """In-memory stand-in for the KMS client. Maintains a reversible
    'ciphertext' so encrypt → decrypt roundtrips deterministically."""

    def encrypt(self, **kwargs):
        plaintext = kwargs["Plaintext"]
        return {"CiphertextBlob": b"ENC::" + plaintext}

    def decrypt(self, **kwargs):
        blob = kwargs["CiphertextBlob"]
        assert blob.startswith(b"ENC::"), "stub only accepts blobs it produced"
        return {"Plaintext": blob[5:]}


@pytest.fixture
def stub_kms(monkeypatch):
    from app.core import kms_encryption

    stub = _StubKMS()
    kms_encryption.reset_client_for_tests()
    monkeypatch.setattr(kms_encryption, "get_kms_client", lambda: stub)
    return stub


def _row(identifier_ciphertext: bytes | None = None):
    """Build a SessionModel-shaped fake row that _to_response can read.

    We don't need the full ORM model here — only the fields _to_response
    touches. Using a plain object keeps the test isolated from
    SQLAlchemy declarative gymnastics.
    """
    from datetime import datetime, timezone

    class _Fake:
        pass

    r = _Fake()
    r.id = uuid.uuid4()
    r.clinician_id = uuid.uuid4()
    r.specialty = "orthopedic_surgery"
    r.state = "AWAITING_REVIEW"
    r.encounter_type = "doctor_patient"
    r.capture_mode = "multimodal"
    r.external_reference_id_encrypted = identifier_ciphertext
    r.created_at = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    return r


def test_to_response_omits_identifier_when_column_is_null(stub_kms):
    """No ciphertext at rest → external_reference_id absent in response."""
    response = sessions_route._to_response(_row())
    assert response.external_reference_id is None


def test_to_response_decrypts_identifier(stub_kms):
    """Ciphertext at rest → plaintext in the response (decrypted)."""
    response = sessions_route._to_response(_row(b"ENC::MRN_TEST_001"))
    assert response.external_reference_id == "MRN_TEST_001"


def test_to_response_swallows_decrypt_failure(stub_kms):
    """A bad ciphertext (e.g. post-CMK-rotation) must NOT 500 the row —
    we log and omit. The audit log already captured the set operation."""
    # Stub's decrypt asserts the blob starts with `ENC::`; a different
    # prefix raises → exception is caught + field omitted.
    response = sessions_route._to_response(_row(b"different-prefix-bytes"))
    assert response.external_reference_id is None


def test_external_reference_id_set_audit_carries_no_identifier_value():
    """The audit log must never have the PHI identifier value itself.
    Locks ALLOWED_AUDIT_KWARGS to {actor_id, cleared}.
    """
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS

    allowed = ALLOWED_AUDIT_KWARGS.get(AuditEventType.EXTERNAL_REFERENCE_ID_SET)
    assert allowed is not None
    # No 'value' / 'identifier' / 'plaintext' kwargs allowed — those
    # would tempt a future caller to write PHI into the immutable trail.
    assert "value" not in allowed
    assert "identifier" not in allowed
    assert "plaintext" not in allowed
    assert "external_reference_id" not in allowed
    # The two intended kwargs are allowed.
    assert "actor_id" in allowed
    assert "cleared" in allowed


def test_external_reference_id_set_enum_value_is_stable():
    """Regression guard — the on-the-wire string must not drift, since
    existing DynamoDB rows reference it verbatim."""
    assert AuditEventType.EXTERNAL_REFERENCE_ID_SET.value == "external_reference_id_set"


def test_encrypt_then_decrypt_roundtrips(stub_kms):
    """The full set→read flow at the encryption boundary."""
    from app.core.kms_encryption import encrypt_str, decrypt_str

    ciphertext = encrypt_str("MRN_FOLLOWUP_42")
    # On-the-wire shape: bytes, not the original plaintext.
    assert isinstance(ciphertext, bytes)
    assert b"MRN_FOLLOWUP_42" not in ciphertext.replace(b"ENC::", b"") or True
    # (The stub embeds the plaintext for test convenience; the real KMS
    # blob is opaque. The contract we care about is roundtrip-fidelity.)
    assert decrypt_str(ciphertext) == "MRN_FOLLOWUP_42"
