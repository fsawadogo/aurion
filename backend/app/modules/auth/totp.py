"""TOTP enrollment + verification (AUTH-PIVOT-BACKEND).

Wraps the ``pyotp`` library in a thin, mockable surface so the auth
routes never reach for the library directly. Three operations:

* ``generate_secret`` — fresh base32 secret for enrollment.
* ``provisioning_uri`` — the ``otpauth://`` URI the authenticator app
  consumes (Apple Passwords, 1Password, Google Authenticator).
* ``verify_code`` — constant-time verify with ±1 window for 30s clock
  skew.

The secret is base32 (matches the otpauth spec). Persistence is the
caller's job — see ``UserModel.mfa_secret_encrypted`` for the KMS-
backed at-rest storage shape. Plaintext secrets never get logged.
"""

from __future__ import annotations

import pyotp

ISSUER = "Aurion"
DRIFT_WINDOWS = 1  # ±1 → accepts the previous and next 30s windows


def generate_secret() -> str:
    """Return a fresh random base32 TOTP secret (160 bits, the otpauth
    default). Each enrollment gets its own secret; never reused."""
    return pyotp.random_base32()


def provisioning_uri(*, email: str, secret: str) -> str:
    """Build the ``otpauth://`` URI an authenticator app scans.

    Format mirrors the de-facto standard the major authenticator apps
    expect: ``otpauth://totp/Aurion:<email>?secret=<base32>&issuer=Aurion``.
    The email is the per-user label; ``issuer`` is the app-wide label
    that appears as the row title.

    The email here is the user's login email — it's PHI-adjacent (it
    identifies a specific clinician) and goes into the URI that the
    user copies to their phone. NOT logged. NOT in any audit row.
    """
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=ISSUER)


def verify_code(*, secret: str, code: str) -> bool:
    """Constant-time TOTP verify with ±1 window for clock skew.

    Returns False if the code is the wrong length, contains non-digits,
    or doesn't match the secret in the current ±1 30s windows.
    ``pyotp.TOTP.verify`` does the constant-time comparison internally;
    the ``valid_window`` kwarg widens the acceptance to the immediately
    previous + next slots, which absorbs phone-clock drift up to ~30s.

    A higher drift would weaken the security model; a zero drift would
    cause spurious rejection during normal clock sync. ±1 is the
    industry default.
    """
    if not code or not code.isdigit() or len(code) != 6:
        return False
    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=DRIFT_WINDOWS))
    except (ValueError, TypeError):
        return False


__all__ = [
    "ISSUER",
    "DRIFT_WINDOWS",
    "generate_secret",
    "provisioning_uri",
    "verify_code",
]
