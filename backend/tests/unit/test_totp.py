"""Unit tests for ``app.modules.auth.totp`` (AUTH-PIVOT-BACKEND)."""

from __future__ import annotations

import re

import pyotp

from app.modules.auth import totp


def test_generate_secret_returns_valid_base32() -> None:
    secret = totp.generate_secret()
    assert isinstance(secret, str)
    # pyotp's default secret length is 32 base32 chars (160 bits).
    assert len(secret) == 32
    # Base32 alphabet — letters A-Z + digits 2-7, no padding for fresh
    # secrets at this length.
    assert re.fullmatch(r"[A-Z2-7]+", secret), secret


def test_provisioning_uri_format() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    uri = totp.provisioning_uri(email="perry@creoq.ca", secret=secret)
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "issuer=Aurion" in uri
    # The email is URL-encoded; the @ becomes %40.
    assert "perry%40creoq.ca" in uri


def test_verify_code_accepts_current_window() -> None:
    secret = totp.generate_secret()
    code = pyotp.TOTP(secret).now()
    assert totp.verify_code(secret=secret, code=code) is True


def test_verify_code_accepts_drift_plus_minus_one() -> None:
    """The ±1 valid_window absorbs ≤30s phone-clock drift."""
    secret = totp.generate_secret()
    t = pyotp.TOTP(secret)
    import time

    now = int(time.time())
    # +30s window (next slot)
    assert totp.verify_code(secret=secret, code=t.at(now + 30)) is True
    # -30s window (previous slot)
    assert totp.verify_code(secret=secret, code=t.at(now - 30)) is True


def test_verify_code_rejects_drift_plus_or_minus_two() -> None:
    """At ±60s (two windows) the code must be rejected."""
    secret = totp.generate_secret()
    t = pyotp.TOTP(secret)
    import time

    now = int(time.time())
    assert totp.verify_code(secret=secret, code=t.at(now + 60)) is False
    assert totp.verify_code(secret=secret, code=t.at(now - 60)) is False


def test_verify_code_rejects_obviously_wrong_inputs() -> None:
    secret = totp.generate_secret()
    assert totp.verify_code(secret=secret, code="") is False
    assert totp.verify_code(secret=secret, code="abc") is False
    assert totp.verify_code(secret=secret, code="12345") is False  # 5 digits
    assert totp.verify_code(secret=secret, code="1234567") is False  # 7 digits
    assert totp.verify_code(secret=secret, code="abcdef") is False  # not digits
    # A random 6-digit code should not match (probabilistically near-certain).
    assert totp.verify_code(secret=secret, code="000000") is False


def test_provisioning_uri_carries_issuer_label() -> None:
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(email="x@y.z", secret=secret)
    # The issuer string appears both as a query param AND the path label
    # — that's how authenticator apps render the row title.
    assert "Aurion" in uri
