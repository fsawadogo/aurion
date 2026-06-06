"""Clinician-scoped MFA + active-session management (issue #163).

The portal `/portal/profile/account` Security card needs three things
that don't have a clinician-facing endpoint yet:

* ``MfaCard`` — enroll / disable, with the canonical 2-step QR-code
  flow + 8 recovery codes returned at enrollment.
* ``SessionsCard`` — list the caller's active refresh-token rows with
  per-row revoke + "Sign out everywhere".
* ``MFA status indicator`` on the card header (enrolled? last verified?).

This router exists separately from ``me.py`` because that file is
already 1700+ lines and the security surface is conceptually
self-contained — every endpoint touches `users.mfa_*` or
`refresh_tokens` rows for the calling clinician and nothing else.

All endpoints:

* require a CLINICIAN bearer (re-uses ``get_current_clinician`` so the
  /me/* role gate is the single source of truth).
* are row-scoped — a clinician sees and acts on their own rows only;
  another clinician's row id returns 404.
* emit one audit event per state change.

Pre-pivot context
-----------------
Issue #163 was filed before PR #234 (auth pivot) and references the
Cognito ``MFA_REQUIRED`` attribute + ``AdminUserGlobalSignOut``. Those
references are stale; this router uses the backend-issued JWT path:

* MFA lives in ``users.mfa_secret_encrypted`` /
  ``users.mfa_enrolled_at`` / ``users.mfa_recovery_codes_hashed``.
* "Active sessions" = rows in ``refresh_tokens``. Revoke = setting
  ``revoked_at = utcnow()`` on the row; the next request on that
  token 401s because ``_find_active_refresh_row`` filters
  ``revoked_at IS NULL``.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.api.v1.me import get_current_clinician
from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.database import get_db
from app.core.kms_encryption import decrypt_str, encrypt_str
from app.core.models import RefreshTokenModel, UserModel
from app.modules.auth import totp
from app.modules.auth.device_hint import ip_class
from app.modules.auth.passwords import hash_password
from app.modules.auth.service import CurrentUser

logger = logging.getLogger("aurion.api.me.security")

# The setup-token JWT is signed with the same key as the rest of the
# auth surface so the secret-management story stays single. We import
# locally to avoid a circular ``app.api.v1.auth`` <-> ``app.api.v1.me``
# dependency chain at module load — the private symbols below are kept
# tiny and explicit so reviewers can audit the JWT shape in one place.
from app.modules.auth.jwt_tokens import _SIGNING_KEY  # noqa: E402

_SETUP_TOKEN_ALGORITHM = "HS256"
_SETUP_TOKEN_TTL_SECONDS = 5 * 60          # 5 minutes
_SETUP_TOKEN_ISSUER = "aurion-mfa-setup"
_SETUP_TOKEN_AUDIENCE = "aurion-mfa-setup"
_RECOVERY_CODE_COUNT = 8

# Synthetic session id for auth-shaped events — mirrors the convention
# in app.api.v1.auth so /me/mfa/* and /me/sessions/* audit rows live in
# the same logical partition as /auth/* rows.
_AUTH_AUDIT_SESSION = uuid.UUID("00000000-0000-0000-0000-000000000000")

router = APIRouter(prefix="/me", tags=["me.security"])


# ── Schemas ─────────────────────────────────────────────────────────────────


class MfaStatusResponse(BaseModel):
    """Body of GET /me/mfa/status."""

    enrolled: bool
    last_verified_at: str | None


class MfaEnrollResponse(BaseModel):
    """Body of POST /me/mfa/enroll.

    ``setup_token`` is a 5-minute JWT wrapping the candidate secret +
    bcrypt-hashed recovery codes. The clinician submits it back to
    /me/mfa/verify-enroll alongside a TOTP code; only then does the
    secret + codes persist. This keeps the user row clean if the
    clinician abandons the flow mid-way.
    """

    qr_uri: str
    secret: str
    recovery_codes: list[str]
    setup_token: str


class MfaVerifyEnrollRequest(BaseModel):
    setup_token: str
    code: str = Field(min_length=6, max_length=6)


class MfaDisableRequest(BaseModel):
    current_code: str = Field(min_length=6, max_length=6)


class SessionRowResponse(BaseModel):
    """Body of one row in GET /me/sessions."""

    id: str
    device_hint: str
    ip_class: str
    created_at: str
    last_used_at: str | None
    is_current: bool


# ── MFA ─────────────────────────────────────────────────────────────────────


@router.get("/mfa/status", response_model=MfaStatusResponse)
async def get_mfa_status(
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> MfaStatusResponse:
    """Return the calling clinician's MFA enrollment state.

    Cheap read — no decrypt, no audit emission. Backs the portal MFA
    card header indicator (enrolled badge + "last verified" line).
    """
    user = await db.get(UserModel, current.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return MfaStatusResponse(
        enrolled=user.mfa_enrolled_at is not None,
        last_verified_at=(
            user.mfa_last_verified_at.isoformat()
            if user.mfa_last_verified_at
            else None
        ),
    )


@router.post("/mfa/enroll", response_model=MfaEnrollResponse)
async def enroll_mfa(
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> MfaEnrollResponse:
    """Start MFA enrollment — generate a candidate secret + 8 recovery codes.

    NOTHING persists on this call. The candidate secret + the bcrypt-
    hashed recovery codes are bundled into a 5-minute signed
    ``setup_token``; the clinician must POST that back to
    /me/mfa/verify-enroll with a valid TOTP code before anything
    sticks. This keeps abandoned-mid-flow users from accidentally
    locking themselves out.

    Recovery codes are returned in plaintext exactly ONCE — the
    portal renders them, the clinician saves them out-of-band. The
    DB only sees the bcrypt hashes after verify-enroll succeeds.
    """
    user = await db.get(UserModel, current.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.mfa_enrolled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "MFA already enrolled. Disable it first before re-enrolling."
            ),
        )

    secret = totp.generate_secret()
    plaintext_codes = [_generate_recovery_code() for _ in range(_RECOVERY_CODE_COUNT)]
    hashed_codes = [hash_password(c) for c in plaintext_codes]

    setup_token = _mint_setup_token(
        user_id=user.id,
        secret=secret,
        hashed_codes=hashed_codes,
    )

    return MfaEnrollResponse(
        qr_uri=totp.provisioning_uri(email=user.email, secret=secret),
        secret=secret,
        recovery_codes=plaintext_codes,
        setup_token=setup_token,
    )


@router.post("/mfa/verify-enroll", status_code=status.HTTP_204_NO_CONTENT)
async def verify_enroll_mfa(
    body: MfaVerifyEnrollRequest,
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Finalize enrollment — persist the candidate secret + hashed codes.

    Decodes the 5-minute setup_token, verifies it was issued for the
    same user, then validates the TOTP code against the candidate
    secret. On success: encrypts + writes the secret, writes the
    hashed recovery codes, marks ``mfa_enrolled_at = now``, emits
    MFA_ENROLLED.

    Failure modes: expired setup_token → 400, mismatched user → 401,
    bad TOTP → 400. None of these tell the attacker which condition
    failed beyond the HTTP status — the detail strings are intentional.
    """
    user = await db.get(UserModel, current.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.mfa_enrolled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA already enrolled.",
        )

    payload = _decode_setup_token(body.setup_token)
    if payload is None or payload["user_id"] != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enrollment session expired. Restart MFA setup.",
        )

    if not totp.verify_code(secret=payload["secret"], code=body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code. Try again.",
        )

    now = utcnow()
    user.mfa_secret_encrypted = encrypt_str(payload["secret"])
    user.mfa_recovery_codes_hashed = payload["hashed_codes"]
    user.mfa_enrolled_at = now
    user.mfa_last_verified_at = now
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.MFA_ENROLLED,
        actor_id=str(user.id),
    )
    await db.flush()
    return None


@router.delete("/mfa", status_code=status.HTTP_204_NO_CONTENT)
async def disable_mfa(
    body: MfaDisableRequest,
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Self-serve disable — wipes the secret + codes after a fresh TOTP verify.

    Re-verification is mandatory: a stolen-laptop attacker with a
    valid access token must not be able to disable MFA without also
    holding the authenticator. The code is checked against the
    persisted secret (NOT against a recovery code — recovery codes
    are intentionally one-way out, not a credential channel).
    """
    user = await db.get(UserModel, current.user_id)
    if user is None or user.mfa_enrolled_at is None or user.mfa_secret_encrypted is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enrolled on this account.",
        )

    secret = decrypt_str(user.mfa_secret_encrypted)
    if not totp.verify_code(secret=secret, code=body.current_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code. Try again.",
        )

    user.mfa_secret_encrypted = None
    user.mfa_recovery_codes_hashed = None
    user.mfa_enrolled_at = None
    user.mfa_last_verified_at = utcnow()
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.MFA_DISABLED,
        actor_id=str(user.id),
    )
    await db.flush()
    return None


# ── Sessions ────────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[SessionRowResponse])
async def list_my_sessions(
    request: Request,
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> list[SessionRowResponse]:
    """Return the calling clinician's active refresh-token rows.

    Filters:
      * user_id == current.user_id (row-level scoping)
      * revoked_at IS NULL          (only live rows)
      * expires_at > now()          (drop expired)

    Each row carries the new portal-friendly metadata:
      * ``device_hint`` — derived UA fingerprint (e.g. "Safari · macOS").
        Falls back to "Unknown device" for pre-migration rows that
        don't have the column populated.
      * ``ip_class`` — coarse local|private|internet|unknown bucket.
        The raw IP is hashed (``issued_ip_hash``); we re-derive
        ``ip_class`` from the current request's client when listing —
        a quick proxy for "do these rows look right". For non-current
        rows we cannot recover ip_class (the raw IP isn't stored), so
        the field is reported as "unknown" for those.
      * ``is_current`` — True for the row whose ``access_token_jti``
        matches the JTI of the bearer token the caller used.
    """
    now = utcnow()
    stmt = (
        select(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == current.user_id,
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > now,
        )
        .order_by(RefreshTokenModel.last_used_at.desc().nulls_last())
    )
    rows = (await db.execute(stmt)).scalars().all()

    current_jti = current.access_token_jti
    current_client_ip = (
        request.client.host if request and request.client else None
    )

    out: list[SessionRowResponse] = []
    for row in rows:
        is_current = (
            current_jti is not None
            and row.access_token_jti is not None
            and row.access_token_jti == current_jti
        )
        out.append(
            SessionRowResponse(
                id=str(row.id),
                device_hint=row.device_hint or "Unknown device",
                # Only the row that matches the caller has a known
                # client_ip; older rows fall back to "unknown" because
                # we never store the raw IP.
                ip_class=ip_class(current_client_ip) if is_current else "unknown",
                created_at=row.issued_at.isoformat(),
                last_used_at=(
                    row.last_used_at.isoformat() if row.last_used_at else None
                ),
                is_current=is_current,
            )
        )
    return out


@router.post(
    "/sessions/{session_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_session(
    session_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-revoke a single refresh-token row owned by the caller.

    Sets ``revoked_at = utcnow()``. The next /auth/refresh or any
    request made with the access token minted from this refresh will
    fail (the access token expires within 30 minutes; the refresh
    row is dead immediately).

    A row that doesn't exist OR belongs to another user surfaces as
    404 — leaking whether row X exists for someone else is a soft
    enumeration vector we'd rather close.
    """
    row = await db.get(RefreshTokenModel, session_id)
    if row is None or row.user_id != current.user_id or row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found."
        )

    row.revoked_at = utcnow()
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.SESSION_REVOKED,
        actor_id=str(current.user_id),
        token_id=str(row.id),
    )
    await db.flush()
    return None


@router.post(
    "/sessions/revoke-all",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_all_sessions(
    current: CurrentUser = Depends(get_current_clinician),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke every active refresh row for the caller EXCEPT the one
    used to make this call.

    The "EXCEPT current" rule is what differentiates this from
    "log out everywhere including me, I'm done for the day" — the
    portal CTA is "Sign out everywhere else", phrased so the
    clinician keeps using the same browser tab while orphan sessions
    elsewhere terminate immediately.

    If the caller's bearer doesn't carry a JTI (pre-#163 access
    token), we keep the most-recently-used active row instead. This
    avoids the worst-case outcome of locking the caller's own
    browser out during a migration.
    """
    now = utcnow()
    current_jti = current.access_token_jti

    stmt = (
        select(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == current.user_id,
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > now,
        )
        .order_by(RefreshTokenModel.last_used_at.desc().nulls_last())
    )
    rows = list((await db.execute(stmt)).scalars().all())

    # Decide which row to keep — preference order: matching JTI →
    # most recently used.
    keep_id: uuid.UUID | None = None
    if current_jti is not None:
        for row in rows:
            if row.access_token_jti == current_jti:
                keep_id = row.id
                break
    if keep_id is None and rows:
        keep_id = rows[0].id

    revoked_count = 0
    for row in rows:
        if row.id == keep_id:
            continue
        row.revoked_at = now
        revoked_count += 1

    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.SESSIONS_REVOKED_ALL,
        actor_id=str(current.user_id),
        count=revoked_count,
    )
    await db.flush()
    return None


# ── Internals ───────────────────────────────────────────────────────────────


def _generate_recovery_code() -> str:
    """Return a single human-friendly recovery code.

    Format: ``XXXX-XXXX`` (8 base32 chars in two dash-separated
    chunks). Ambiguous characters (0, 1, O, I, L) are stripped from
    the alphabet so dictation transcription errors are rare. Entropy:
    8 chars × 5 bits ≈ 40 bits per code, 8 codes per user.
    """
    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _mint_setup_token(
    *, user_id: uuid.UUID, secret: str, hashed_codes: list[str]
) -> str:
    """Wrap the candidate secret + hashed recovery codes into a 5-minute JWT.

    Signed with the same key as the rest of the auth surface (HS256).
    Carries:
      * sub  = user_id
      * sec  = candidate TOTP secret (base32)
      * codes = bcrypt hashes of the recovery codes
      * exp  = now + 5 minutes
      * iss/aud bound to this flow so a regular access token can't
        be replayed as a setup token.

    The secret + hashes ride the wire because storing them server-
    side before verification would mean every abandoned enrollment
    leaves a half-written row. The 5-minute TTL bounds the exposure
    window; the JWT signature prevents tampering.
    """
    now = int(utcnow().timestamp())
    claims = {
        "sub": str(user_id),
        "sec": secret,
        "codes": hashed_codes,
        "iat": now,
        "exp": now + _SETUP_TOKEN_TTL_SECONDS,
        "iss": _SETUP_TOKEN_ISSUER,
        "aud": _SETUP_TOKEN_AUDIENCE,
        "type": "mfa_setup",
    }
    return jwt.encode(claims, _SIGNING_KEY, algorithm=_SETUP_TOKEN_ALGORITHM)


def _decode_setup_token(
    token: str,
) -> dict | None:
    """Verify a setup_token; ``None`` on any failure (expired, bad
    signature, wrong type, mismatched audience).

    Returns a dict with the decoded fields the caller needs:
    ``{"user_id": str, "secret": str, "hashed_codes": list[str]}``.
    """
    try:
        claims = jwt.decode(
            token,
            _SIGNING_KEY,
            algorithms=[_SETUP_TOKEN_ALGORITHM],
            audience=_SETUP_TOKEN_AUDIENCE,
            issuer=_SETUP_TOKEN_ISSUER,
        )
    except JWTError:
        return None
    if claims.get("type") != "mfa_setup":
        return None
    try:
        return {
            "user_id": claims["sub"],
            "secret": claims["sec"],
            "hashed_codes": list(claims["codes"]),
        }
    except (KeyError, TypeError):
        return None
