"""Unit tests for :mod:`app.core.identifier_hash`.

The hash function is the single source of truth for the indexed
patient-identifier lookup (#61, full slice). These tests lock the
three invariants every downstream caller (PATCH /sessions/{id}/
identifier, GET /me/patients/{identifier}/sessions, longitudinal
context loader) relies on:

  1. Determinism — same plaintext + same key → same digest, every call.
  2. HMAC-vs-plain-SHA256 — the hash is keyed, not a bare digest. An
     attacker who scrapes the column without the key cannot match
     anything via a precomputed rainbow table.
  3. Per-key uniqueness — rotating the key changes every digest.
     Foundation for the future dual-write rotation window.

Plus a safety case: empty input raises so an empty identifier never
silently maps every empty session to the same matchable digest.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import pytest

from app.core import identifier_hash
from app.core.identifier_hash import hash_identifier


@pytest.fixture(autouse=True)
def _stub_hmac_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop in a deterministic HMAC key for every test.

    The production code reads the key from Secrets Manager on first
    use and caches it for the process lifetime. Tests must reset the
    cache and override the env var so a previous test's cached key
    doesn't bleed into the next.
    """
    monkeypatch.setenv("AURION_IDENTIFIER_HMAC_KEY", "unit-test-key-A")
    identifier_hash.reset_cache_for_tests()
    yield
    identifier_hash.reset_cache_for_tests()


def test_hash_is_deterministic() -> None:
    """Same input → same output, regardless of how many times we call."""
    first = hash_identifier("MRN-12345")
    second = hash_identifier("MRN-12345")
    third = hash_identifier("MRN-12345")
    assert first == second == third
    # 32-byte digest matches SHA-256's output width — the schema's
    # column expects exactly this.
    assert len(first) == 32


def test_different_inputs_produce_different_digests() -> None:
    """Hash collisions across plausible MRN-shaped strings would mix
    different patients' rails together; HMAC-SHA256 is collision-
    resistant but we exercise this end-to-end to lock the contract."""
    a = hash_identifier("MRN-12345")
    b = hash_identifier("MRN-12346")  # one character off
    c = hash_identifier("mrn-12345")  # lowercase
    assert a != b
    assert a != c  # case-sensitive lookup, as the API doc promises


def test_hash_uses_hmac_not_plain_sha256() -> None:
    """Known-answer test. Asserts the function delegates to
    HMAC-SHA256 with the configured key, NOT to a bare SHA-256.

    Plain SHA-256 of "MRN-12345" is publicly computable; HMAC's
    output diverges for any non-empty key. Comparing both rules out
    the regression where someone "simplifies" the function back to
    ``hashlib.sha256(...).digest()`` for performance.
    """
    plaintext = "MRN-12345"
    key = b"unit-test-key-A"

    plain_sha256 = hashlib.sha256(plaintext.encode("utf-8")).digest()
    expected_hmac = hmac.new(key, plaintext.encode("utf-8"), hashlib.sha256).digest()

    actual = hash_identifier(plaintext)

    assert actual == expected_hmac, "hash_identifier must use HMAC-SHA256"
    assert actual != plain_sha256, (
        "hash_identifier must NOT be a bare SHA-256 — that would let an "
        "attacker brute-force the column with a precomputed table"
    )


def test_hash_differs_per_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rotating the HMAC key MUST change every digest. This is the
    invariant the future dual-write rotation will depend on: the old
    column is unreadable to the new key, the new column is unreadable
    to the old key, and the back-fill window has to write both."""
    monkeypatch.setenv("AURION_IDENTIFIER_HMAC_KEY", "unit-test-key-A")
    identifier_hash.reset_cache_for_tests()
    with_key_a = hash_identifier("MRN-12345")

    monkeypatch.setenv("AURION_IDENTIFIER_HMAC_KEY", "unit-test-key-B")
    identifier_hash.reset_cache_for_tests()
    with_key_b = hash_identifier("MRN-12345")

    assert with_key_a != with_key_b


def test_empty_input_raises() -> None:
    """Empty plaintext is a programming error. The contract is "call
    sites NULL the column instead"; returning a fixed digest would
    make every empty-identifier row hash-match every other empty-
    identifier row, which would silently leak across patients in the
    indexed lookup."""
    with pytest.raises(ValueError):
        hash_identifier("")


def test_env_var_override_is_decoded_as_bytes() -> None:
    """The override path accepts either base64 or raw UTF-8. Either
    way the resulting digest must be reproducible from the documented
    HMAC-SHA256 rule with the same bytes used as the key.

    Locks the dev-stub path so a developer's local key (which is
    typically NOT base64) keeps producing a stable digest across
    process restarts.
    """
    raw_key_text = "raw-utf8-stub-not-base64"
    os.environ["AURION_IDENTIFIER_HMAC_KEY"] = raw_key_text
    identifier_hash.reset_cache_for_tests()

    expected = hmac.new(
        raw_key_text.encode("utf-8"),
        b"MRN-9",
        hashlib.sha256,
    ).digest()
    assert hash_identifier("MRN-9") == expected
