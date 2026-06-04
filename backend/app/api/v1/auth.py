"""Auth API routes — backend-issued JWT + TOTP MFA + email-link reset.

AUTH-PIVOT-BACKEND. This router replaces the Cognito hosted UI flow.
The dev-only ``APP_ENV=local`` 503 gates around /login and /register
are gone; /register itself is gone (admin creates users now). The
single source of truth for "who can sign in?" is this router; the
``users`` table is the persistent identity, and the audit log is the
immutable behaviour trail.

Endpoint surface
----------------
``POST /api/v1/auth/login``                  email + password
``POST /api/v1/auth/mfa/verify-login``       complete an MFA-gated login
``POST /api/v1/auth/refresh``                refresh-token rotation
``POST /api/v1/auth/logout``                 revoke current refresh
``POST /api/v1/auth/forgot-password``        always 204 (account-existence safe)
``POST /api/v1/auth/reset-password``         consume a reset token
``GET  /api/v1/auth/mfa/setup``              issue secret + provisioning URI
``POST /api/v1/auth/mfa/setup/verify``       enroll with a valid code
``DELETE /api/v1/auth/mfa``                  admin-only — clear a user's MFA
``GET  /api/v1/auth/me``                     current user
``POST /api/v1/auth/dev/seed-users``         legacy dev path (still seeds the 6 accounts)

Critical hygiene (see CLAUDE.md):
* All login failures return identical error JSON. No account enumeration.
* /forgot-password never reveals account existence.
* Lockouts are observable only through the audit log.
* MFA secrets KMS-encrypted at rest, never logged.
* Refresh + reset raw tokens NEVER logged; only their UUID row id reaches audit.
* Every auth state change emits an audit event from the auth-pivot whitelist.
"""

from __future__ import annotations

import logging
import os
import secrets
import string
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.database import async_session_factory, get_db
from app.core.kms_encryption import decrypt_str, encrypt_str
from app.core.models import RefreshTokenModel, UserModel
from app.core.types import UserRole
from app.modules.auth import lockout, password_reset, totp
from app.modules.auth.email import send_password_reset_email
from app.modules.auth.jwt_tokens import (
    REFRESH_TOKEN_TTL_SECONDS,
    compare_token_hashes,
    hash_ip,
    hash_refresh_token,
    mint_access_token,
    mint_mfa_challenge_token,
    mint_refresh_token,
    verify_mfa_challenge_token,
)
from app.modules.auth.passwords import hash_password, verify_password
from app.modules.auth.service import CurrentUser, get_current_user, require_role

logger = logging.getLogger("aurion.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

def _is_local_env() -> bool:
    """Per-call APP_ENV lookup. Reading at module import would pin the
    value at first-import, which the auth integration tests need to
    override after pytest has loaded ``app.main``."""
    return os.getenv("APP_ENV", "local") == "local"

# Synthetic session id for auth events — auth events are not session-
# scoped (a single user issues N login events across M sessions over
# time). Same convention as PROMPT_USER_PROMPT_* and VISION_CLIP_PROBED.
_AUTH_AUDIT_SESSION = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Bcrypt hash used as a constant-time dummy when no user is found, so
# the response time of "unknown user" matches "bad password". Computed
# once at import; the plaintext is not the dummy's value — we only need
# `bcrypt.checkpw` to do a real work-factor verification on the wrong
# input. The dummy's hash itself is harmless because it's never stored.
_DUMMY_PASSWORD_HASH = hash_password("constant-time-dummy-never-stored")


# ── Dev seed accounts (kept; the dev-token integration tests rely on these) ─


@dataclass(frozen=True, slots=True)
class _DevUser:
    password: str
    user_id: str
    full_name: str
    role: UserRole
    voice_enrolled: bool = False


_DEV_USERS: dict[str, _DevUser] = {
    "admin@aurionclinical.com": _DevUser(
        password="admin",
        user_id="00000000-0000-0000-0000-000000000000",
        full_name="Admin",
        role=UserRole.ADMIN,
    ),
    "perry@creoq.ca": _DevUser(
        password="perry",
        user_id="00000000-0000-0000-0000-000000000001",
        full_name="Dr. Perry Gdalevitch",
        role=UserRole.CLINICIAN,
        voice_enrolled=True,
    ),
    "marie@creoq.ca": _DevUser(
        password="marie",
        user_id="00000000-0000-0000-0000-000000000002",
        full_name="Dr. Marie Gdalevitch",
        role=UserRole.CLINICIAN,
    ),
    "compliance@aurionclinical.com": _DevUser(
        password="compliance",
        user_id="00000000-0000-0000-0000-000000000003",
        full_name="Compliance Officer",
        role=UserRole.COMPLIANCE_OFFICER,
    ),
    "eval@aurionclinical.com": _DevUser(
        password="eval",
        user_id="00000000-0000-0000-0000-000000000004",
        full_name="Eval Reviewer",
        role=UserRole.EVAL_TEAM,
    ),
    "demo@aurion.health": _DevUser(
        password="demo1234",
        user_id="00000000-0000-0000-0000-000000000005",
        full_name="Dr. Antoine Tremblay",
        role=UserRole.CLINICIAN,
    ),
}


# ── Schemas ─────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class UserPayload(BaseModel):
    user_id: str
    email: str
    role: str
    full_name: str
    mfa_enrolled: bool


class LoginSuccessResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserPayload


class LoginMfaRequiredResponse(BaseModel):
    mfa_required: bool = True
    mfa_challenge_token: str
    user_email: str


class MfaVerifyLoginRequest(BaseModel):
    mfa_challenge_token: str
    code: str = Field(min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaSetupVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class MfaClearRequest(BaseModel):
    user_id: str


class CurrentUserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    mfa_enrolled: bool = False


# ── Constants ───────────────────────────────────────────────────────────────


_GENERIC_LOGIN_FAILURE = "Invalid email or password."


# ── /login ──────────────────────────────────────────────────────────────────


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate against the users table.

    Resolution:
      1. Look up user by lower-cased email; constant-time bcrypt verify
         on success OR on a dummy hash on miss (matches response time).
      2. If account inactive or locked, return the same 401 as wrong
         password. Lockouts emit a LOGIN_LOCKED audit, not visible to
         the attacker.
      3. If MFA enrolled, return mfa_required + a 5-minute challenge
         token; the login is NOT yet complete.
      4. Otherwise, mint access + refresh, persist the refresh-hash row,
         emit LOGIN_SUCCESS + REFRESH_TOKEN_ISSUED.
    """
    user = await _find_user_by_email(db, body.email)

    # Constant-time bcrypt against either the user's hash or a dummy.
    password_ok = verify_password(
        body.password,
        user.password_hash if user else _DUMMY_PASSWORD_HASH,
    )

    if user is None or not password_ok or not user.is_active:
        if user is not None:
            # Track failure / lockout — every failure path runs through
            # the same audit branch so the attacker can't time-distinguish
            # wrong-password from no-such-user from inactive.
            crossed = lockout.record_failure(user)
            await write_audit(
                _AUTH_AUDIT_SESSION,
                AuditEventType.LOGIN_FAILURE,
                target_user_id=str(user.id),
                reason="inactive" if not user.is_active else "bad_password",
            )
            if crossed:
                await write_audit(
                    _AUTH_AUDIT_SESSION,
                    AuditEventType.LOGIN_LOCKED,
                    target_user_id=str(user.id),
                    failed_count=user.failed_login_count,
                )
            await db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_LOGIN_FAILURE,
        )

    # Lockout gate AFTER password verify — we don't want to short-circuit
    # before verifying the password, otherwise the response time of a
    # locked vs unlocked user differs by a bcrypt round.
    if lockout.is_locked(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_LOGIN_FAILURE,
        )

    # MFA gate — if enrolled, return the challenge token instead of
    # finishing the login. The challenge wraps user_id + 5-minute exp.
    if user.mfa_enrolled_at is not None:
        challenge = mint_mfa_challenge_token(
            user_id=user.id, email=user.email
        )
        return LoginMfaRequiredResponse(
            mfa_challenge_token=challenge,
            user_email=user.email,
        )

    # Happy path — clear lockout, mint tokens, persist refresh, audit.
    lockout.record_success(user)
    user.last_login_at = utcnow()
    return await _issue_tokens_and_persist(db, user, request)


# ── /mfa/verify-login ───────────────────────────────────────────────────────


@router.post("/mfa/verify-login")
async def mfa_verify_login(
    body: MfaVerifyLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Finalize an MFA-gated login. The challenge token proves the
    caller passed the password gate; this call proves they have the
    authenticator. Bad code → same 401 as anywhere else."""
    challenge = verify_mfa_challenge_token(body.mfa_challenge_token)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_LOGIN_FAILURE,
        )

    user = await db.get(UserModel, challenge.user_id)
    if (
        user is None
        or not user.is_active
        or user.mfa_secret_encrypted is None
        or user.mfa_enrolled_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_LOGIN_FAILURE,
        )

    secret = decrypt_str(user.mfa_secret_encrypted)
    if not totp.verify_code(secret=secret, code=body.code):
        # MFA verify failures count toward the lockout window same as
        # password failures — otherwise an attacker who phished the
        # password could brute-force TOTP unlimited times.
        crossed = lockout.record_failure(user)
        await write_audit(
            _AUTH_AUDIT_SESSION,
            AuditEventType.LOGIN_FAILURE,
            target_user_id=str(user.id),
            reason="bad_password",  # generic — same enum value
        )
        if crossed:
            await write_audit(
                _AUTH_AUDIT_SESSION,
                AuditEventType.LOGIN_LOCKED,
                target_user_id=str(user.id),
                failed_count=user.failed_login_count,
            )
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_LOGIN_FAILURE,
        )

    lockout.record_success(user)
    user.last_login_at = utcnow()
    return await _issue_tokens_and_persist(db, user, request)


# ── /refresh ────────────────────────────────────────────────────────────────


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a refresh token for a new access + rotated refresh.

    Rotation: the presented token is revoked AND a new one is issued in
    the same transaction. Replay of the old token returns 401. This is
    the canonical post-pilot pattern for refresh-token security.
    """
    row, user = await _find_active_refresh_row(db, body.refresh_token)
    if row is None or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    now = utcnow()
    row.revoked_at = now
    previous_token_id = str(row.id)

    new_row, raw_refresh = await _persist_new_refresh_row(db, user, request, now=now)
    access_token, expires_in = mint_access_token(
        user_id=user.id, role=user.role, email=user.email
    )

    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.REFRESH_TOKEN_ROTATED,
        actor_id=str(user.id),
        previous_token_id=previous_token_id,
        new_token_id=str(new_row.id),
    )
    await db.flush()

    return LoginSuccessResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=expires_in,
        user=_user_payload(user),
    )


# ── /logout ─────────────────────────────────────────────────────────────────


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """Revoke a refresh token. Always returns 204 — we don't want to
    confirm whether the token existed (a stolen + already-revoked token
    shouldn't give the attacker a confirmation channel).
    """
    row, user = await _find_active_refresh_row(db, body.refresh_token)
    if row is not None and user is not None:
        row.revoked_at = utcnow()
        await write_audit(
            _AUTH_AUDIT_SESSION,
            AuditEventType.LOGOUT,
            actor_id=str(user.id),
        )
        await write_audit(
            _AUTH_AUDIT_SESSION,
            AuditEventType.REFRESH_TOKEN_REVOKED,
            actor_id=str(user.id),
            token_id=str(row.id),
            reason="logout",
        )
        await db.flush()
    return None


# ── /forgot-password + /reset-password ──────────────────────────────────────


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Issue a reset token + email it. ALWAYS returns 204, no exceptions.

    The 204 fires whether or not the email maps to an account so the
    caller can't enumerate user existence. The audit log records the
    attempt only when a real account was found — there's nothing to
    record for an unknown email.
    """
    user = await _find_user_by_email(db, body.email)
    if user is None or not user.is_active:
        return None

    raw_token, _row = await password_reset.issue_reset_token(db, user)
    await send_password_reset_email(user=user, raw_token=raw_token)
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.PASSWORD_RESET_REQUESTED,
        target_user_id=str(user.id),
    )
    await db.flush()
    return None


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Consume a reset token + set the new password. 400 on any failure
    (expired, consumed, unknown). Successful reset revokes every active
    refresh token for the user — see ``password_reset.verify_and_consume``.
    """
    user = await password_reset.verify_and_consume(db, body.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    user.password_hash = hash_password(body.new_password)
    user.last_password_changed_at = utcnow()
    # The verify_and_consume call already revoked refresh tokens. Reset
    # the lockout counter so a user who reset because they were locked
    # out can sign in immediately.
    lockout.record_success(user)

    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.PASSWORD_CHANGED,
        actor_id=str(user.id),
        via="self_reset",
    )
    await db.flush()
    return None


# ── MFA enrollment ──────────────────────────────────────────────────────────


@router.get("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a fresh TOTP secret + provisioning URI for an unenrolled user.

    The secret is persisted (KMS-encrypted) immediately so the user can
    re-fetch the same URI from a second device during enrollment. The
    enrollment is NOT complete until /mfa/setup/verify succeeds — until
    then, mfa_enrolled_at stays NULL and login skips the MFA gate.
    """
    user = await db.get(UserModel, current.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    if user.mfa_enrolled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA already enrolled. Contact an administrator to reset.",
        )

    secret = totp.generate_secret()
    user.mfa_secret_encrypted = encrypt_str(secret)
    await db.flush()

    return MfaSetupResponse(
        secret=secret,
        provisioning_uri=totp.provisioning_uri(email=user.email, secret=secret),
    )


@router.post("/mfa/setup/verify", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_setup_verify(
    body: MfaSetupVerifyRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm enrollment by submitting a code from the authenticator app."""
    user = await db.get(UserModel, current.user_id)
    if user is None or user.mfa_secret_encrypted is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No MFA enrollment in progress. Call /mfa/setup first.",
        )

    secret = decrypt_str(user.mfa_secret_encrypted)
    if not totp.verify_code(secret=secret, code=body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code. Try again.",
        )

    user.mfa_enrolled_at = utcnow()
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.MFA_ENROLLED,
        actor_id=str(user.id),
    )
    await db.flush()
    return None


@router.delete("/mfa", status_code=status.HTTP_204_NO_CONTENT)
async def admin_clear_mfa(
    body: MfaClearRequest,
    current: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Clear a user's MFA enrollment. ADMIN only — the lost-authenticator path.

    The user is told out-of-band, re-enrolls on next sign-in. We don't
    expose a self-serve "I lost my phone" flow on purpose; that's a
    social-engineering attack surface we deliberately avoid in v1.
    """
    target_id = uuid.UUID(body.user_id)
    target = await db.get(UserModel, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    target.mfa_secret_encrypted = None
    target.mfa_enrolled_at = None
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.MFA_RESET,
        actor_id=str(current.user_id),
        target_user_id=str(target.id),
    )
    await db.flush()
    return None


# ── /me ─────────────────────────────────────────────────────────────────────


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentUserResponse:
    """Canonical identity endpoint. Backend JWT path skips auto-provision
    because /admin/users is the only ingress; legacy Cognito path keeps
    the auto-provision behaviour for the cutover window."""
    user = await db.get(UserModel, current.user_id)
    if user is None:
        # Legacy auto-provision path — only reached during the
        # AUTH_ACCEPT_LEGACY_COGNITO_JWT cutover. Once the flag flips
        # off, this branch is unreachable.
        user = UserModel(
            id=current.user_id,
            email=current.email or f"unknown-{current.user_id}@aurionclinical.com",
            full_name="",
            role=current.role,
            password_hash="",
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User exists with a different identity. Contact admin.",
            )
        logger.info(
            "Auto-provisioned user (legacy Cognito path): id=%s role=%s",
            user.id,
            user.role.value,
        )

    return CurrentUserResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        mfa_enrolled=user.mfa_enrolled_at is not None,
    )


# ── Helpers (private) ───────────────────────────────────────────────────────


async def _find_user_by_email(db: AsyncSession, email: str) -> UserModel | None:
    result = await db.execute(
        select(UserModel).where(UserModel.email == email.lower())
    )
    return result.scalar_one_or_none()


async def _find_active_refresh_row(
    db: AsyncSession, raw_token: str
) -> tuple[RefreshTokenModel | None, UserModel | None]:
    """Look up a non-revoked, non-expired refresh-token row + its user.

    The hash equality both narrows the index AND is double-checked with
    ``compare_token_hashes`` (constant time) — belt and suspenders on
    top of the DB's equality.
    """
    if not raw_token:
        return None, None
    expected = hash_refresh_token(raw_token)
    now = utcnow()
    stmt = select(RefreshTokenModel).where(
        RefreshTokenModel.token_hash == expected,
        RefreshTokenModel.revoked_at.is_(None),
        RefreshTokenModel.expires_at > now,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None, None
    if not compare_token_hashes(row.token_hash, expected):
        return None, None
    user = await db.get(UserModel, row.user_id)
    if user is None or not user.is_active:
        return None, None
    return row, user


async def _persist_new_refresh_row(
    db: AsyncSession,
    user: UserModel,
    request: Request,
    *,
    now=None,
) -> tuple[RefreshTokenModel, str]:
    """Mint a fresh refresh token, persist its hash row, return both.

    The raw token is returned exactly once to the caller (the issuing
    /login or /refresh handler). The row is added to the session;
    commit is the route's job.
    """
    raw, token_hash = mint_refresh_token()
    now = now or utcnow()
    ua = (request.headers.get("user-agent") or "")[:255] if request else ""
    client_ip = request.client.host if request and request.client else ""
    row = RefreshTokenModel(
        user_id=user.id,
        token_hash=token_hash,
        issued_at=now,
        expires_at=now + _refresh_token_ttl(),
        issued_user_agent=ua or None,
        issued_ip_hash=hash_ip(client_ip) if client_ip else None,
    )
    db.add(row)
    await db.flush()
    return row, raw


def _refresh_token_ttl():
    """Indirection so tests can monkeypatch a shorter TTL without rewriting
    the persistence call sites."""
    from datetime import timedelta

    return timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS)


async def _issue_tokens_and_persist(
    db: AsyncSession, user: UserModel, request: Request
) -> LoginSuccessResponse:
    """Common tail of /login and /mfa/verify-login.

    Mints access + refresh, persists the refresh-hash row, emits
    LOGIN_SUCCESS + REFRESH_TOKEN_ISSUED, flushes (route commits).
    """
    new_row, raw_refresh = await _persist_new_refresh_row(db, user, request)
    access_token, expires_in = mint_access_token(
        user_id=user.id, role=user.role, email=user.email
    )

    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.LOGIN_SUCCESS,
        actor_id=str(user.id),
    )
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.REFRESH_TOKEN_ISSUED,
        actor_id=str(user.id),
        token_id=str(new_row.id),
    )
    await db.flush()

    return LoginSuccessResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=expires_in,
        user=_user_payload(user),
    )


def _user_payload(user: UserModel) -> UserPayload:
    return UserPayload(
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
        full_name=user.full_name,
        mfa_enrolled=user.mfa_enrolled_at is not None,
    )


def generate_temp_password(*, length: int = 12) -> str:
    """Generate a temporary password for admin user-create + reset.

    Uses ``secrets.choice`` over a printable-ASCII-minus-ambiguous
    alphabet so a phone-dictated temp password doesn't trip on
    ``O``/``0``/``l``/``1``. Twelve characters at this entropy gives
    ~71 bits, plenty for a single-use credential the user must rotate
    on first sign-in (rotate-on-first-sign-in UI is a follow-up).
    """
    alphabet = (
        string.ascii_uppercase.replace("O", "").replace("I", "")
        + string.ascii_lowercase.replace("l", "").replace("o", "")
        + string.digits.replace("0", "").replace("1", "")
    )
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── Dev seeding ─────────────────────────────────────────────────────────────


async def seed_dev_users() -> None:
    """Idempotent — inserts the 6 seed accounts if their emails are missing.

    Called from main.lifespan on startup so existing dev tokens
    (``ROLE:UUID``) keep resolving to the same user IDs the iOS client
    may have cached. Only runs when ``APP_ENV=local``.
    """
    if not _is_local_env():
        return

    async with async_session_factory() as db:
        for email, dev_user in _DEV_USERS.items():
            existing = await _find_user_by_email(db, email)
            if existing is not None:
                continue
            db.add(
                UserModel(
                    id=uuid.UUID(dev_user.user_id),
                    email=email,
                    password_hash=hash_password(dev_user.password),
                    full_name=dev_user.full_name,
                    role=dev_user.role,
                    voice_enrolled=dev_user.voice_enrolled,
                )
            )
        await db.commit()
