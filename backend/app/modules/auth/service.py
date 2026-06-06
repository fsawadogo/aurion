"""JWT authentication and role-based authorization.

AUTH-PIVOT-BACKEND: the primary path is the backend-issued HS256
token from ``app.modules.auth.jwt_tokens``. The Cognito JWKS path
stays available behind ``AUTH_ACCEPT_LEGACY_COGNITO_JWT=true`` so the
cutover doesn't have to be flag-day; once all clients have moved to
the backend tokens the flag flips off in a follow-up PR and the
JWKS code path is deleted entirely.

In local dev (``APP_ENV=local``) the simple bearer ``<role>:<user_id>``
token is still accepted — most of the integration test suite is built
on it and the iOS dev workflow uses it during the simulator loop.

Resolution order:
  1. ``APP_ENV=local``  → dev token.
  2. Try the backend HS256 access token.
  3. If ``AUTH_ACCEPT_LEGACY_COGNITO_JWT=true``, fall through to Cognito
     JWKS validation.
  4. Otherwise — or if the legacy path also fails — return 401.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth.jwt_tokens import verify_access_token

logger = logging.getLogger("aurion.auth")

_security = HTTPBearer()


def _app_env() -> str:
    """Per-call APP_ENV lookup. Reading at module import time would
    pin the value at first-import, which breaks tests that flip
    ``APP_ENV=production`` after pytest has already loaded ``app.main``."""
    return os.getenv("APP_ENV", "local")


def _accept_legacy_cognito() -> bool:
    return os.getenv("AUTH_ACCEPT_LEGACY_COGNITO_JWT", "false").lower() in (
        "1",
        "true",
        "yes",
    )

# ── Cognito Configuration ────────────────────────────────────────────────

_COGNITO_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
_COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")

# JWKS cache: store the keys and a timestamp for cache invalidation
_jwks_cache: Optional[dict[str, Any]] = None
_jwks_cache_timestamp: float = 0.0
_JWKS_CACHE_TTL_SECONDS = 86400  # 24 hours


class CurrentUser:
    """Represents the authenticated user extracted from JWT.

    ``access_token_jti`` is the JTI claim from the bearer token (set
    for backend-issued HS256 tokens since #163). It links the request
    back to the refresh-token row it was minted from so /me/sessions
    can flag the row as "current". ``None`` for dev tokens and
    legacy Cognito tokens that don't carry the claim.
    """

    def __init__(
        self,
        user_id: uuid.UUID,
        role: UserRole,
        email: str = "",
        access_token_jti: uuid.UUID | None = None,
    ):
        self.user_id = user_id
        self.role = role
        self.email = email
        self.access_token_jti = access_token_jti


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency — extract and validate the current user.

    Resolution order (see module docstring): dev token → backend HS256
    JWT → optional Cognito JWKS legacy fallback. Whichever path
    succeeds runs through ``_ensure_active`` so a deactivated user is
    blocked on the next request regardless of which credential path
    they used.
    """
    token = credentials.credentials

    if _app_env() == "local":
        # In local dev, accept either the dev token shape OR a real
        # backend-issued HS256 access token. The auth integration tests
        # always go through the backend path (they call /auth/login
        # which mints HS256), while the broader test suite continues
        # to pass dev-token bearers (``CLINICIAN:<uuid>``).
        backend_payload = verify_access_token(token)
        if backend_payload is not None:
            user = CurrentUser(
                user_id=backend_payload.user_id,
                role=backend_payload.role,
                email=backend_payload.email,
                access_token_jti=backend_payload.jti,
            )
            await _ensure_active(db, user.user_id)
            return user
        return _parse_dev_token(token)

    # Primary path: backend-issued HS256 access token.
    payload = verify_access_token(token)
    if payload is not None:
        user = CurrentUser(
            user_id=payload.user_id,
            role=payload.role,
            email=payload.email,
            access_token_jti=payload.jti,
        )
        await _ensure_active(db, user.user_id)
        return user

    # Legacy cutover fallback — only attempted while the cutover env
    # flag is on. Once all clients have moved to backend tokens the
    # flag flips off and this branch becomes dead code we delete.
    if _accept_legacy_cognito():
        try:
            user = await _validate_cognito_jwt(token)
            await _ensure_active(db, user.user_id)
            return user
        except HTTPException:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token.",
    )


async def _ensure_active(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Block requests from an admin-deactivated account.

    The token may still be cryptographically valid (Cognito access tokens
    live ~1h), so deactivation is enforced here on every request by checking
    the DB ``is_active`` flag — immediate, no per-user Cognito round-trip.
    A user with no DB row yet (first authenticated call, pre-provisioning)
    is allowed through. The dependency-injected session is shared with the
    route via FastAPI's per-request dependency cache, so this adds no extra
    connection. (Cognito-side AdminDisableUser is a defense-in-depth
    follow-up, tracked separately.)
    """
    result = await db.execute(
        select(UserModel.is_active).where(UserModel.id == user_id)
    )
    is_active = result.scalar_one_or_none()
    if is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated. Contact your administrator.",
        )


def _parse_dev_token(token: str) -> CurrentUser:
    """Parse dev token format: <role>:<user_id> or just <role>."""
    try:
        parts = token.split(":")
        role = UserRole(parts[0].upper())
        user_id = uuid.UUID(parts[1]) if len(parts) > 1 else uuid.uuid4()
        return CurrentUser(user_id=user_id, role=role, email=f"dev-{role.value.lower()}@aurion.local")
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dev token. Format: <role>:<user_id> or <role>",
        )


async def _validate_cognito_jwt(token: str) -> CurrentUser:
    """Validate JWT against Cognito JWKS.

    Steps:
    1. Fetch JWKS from Cognito (cached for 24 hours)
    2. Decode the JWT header to find the key ID (kid)
    3. Find the matching public key in JWKS
    4. Verify the token signature, expiry, issuer, audience
    5. Extract user info: sub, email, cognito:groups
    6. Map Cognito group to UserRole
    """
    # 1. Get JWKS (cached)
    jwks = await _get_jwks()
    if not jwks:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch Cognito JWKS for token verification.",
        )

    # 2. Decode JWT header to get kid
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header.",
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token header missing key ID (kid).",
        )

    # 3. Find matching key in JWKS
    rsa_key: Optional[dict[str, str]] = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            rsa_key = {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }
            break

    if not rsa_key:
        # Key not found — try refreshing JWKS in case keys rotated
        jwks = await _get_jwks(force_refresh=True)
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

    if not rsa_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find matching key for token verification.",
        )

    # 4. Verify and decode the token
    issuer = f"https://cognito-idp.{_COGNITO_REGION}.amazonaws.com/{_COGNITO_USER_POOL_ID}"

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=_COGNITO_CLIENT_ID,
            issuer=issuer,
            options={
                "verify_at_hash": False,
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )
    except JWTError as e:
        logger.warning("JWT verification failed: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed.",
        )

    # 5. Extract user info
    sub = payload.get("sub", "")
    email = payload.get("email", "")

    # 6. Map Cognito group to UserRole
    cognito_groups: list[str] = payload.get("cognito:groups", [])
    role = _resolve_role_from_groups(cognito_groups)

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token.",
        )

    logger.info("Cognito JWT validated: user=%s role=%s", sub, role.value)
    return CurrentUser(user_id=user_id, role=role, email=email)


async def _get_jwks(force_refresh: bool = False) -> dict[str, Any]:
    """Fetch JWKS from Cognito, cached for 24 hours.

    Args:
        force_refresh: If True, ignore cache and fetch fresh JWKS.

    Returns:
        The JWKS dictionary with public keys.
    """
    global _jwks_cache, _jwks_cache_timestamp

    now = time.time()

    # Return cached if still valid
    if (
        not force_refresh
        and _jwks_cache is not None
        and (now - _jwks_cache_timestamp) < _JWKS_CACHE_TTL_SECONDS
    ):
        return _jwks_cache

    # Fetch JWKS from Cognito
    jwks_url = (
        f"https://cognito-idp.{_COGNITO_REGION}.amazonaws.com"
        f"/{_COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks = response.json()

        _jwks_cache = jwks
        _jwks_cache_timestamp = now
        logger.info("JWKS fetched and cached from %s", jwks_url)
        return jwks

    except httpx.HTTPError as e:
        logger.error("Failed to fetch JWKS from %s: %s", jwks_url, str(e))
        # Return stale cache if available
        if _jwks_cache is not None:
            logger.warning("Using stale JWKS cache after fetch failure")
            return _jwks_cache
        return {}


def _resolve_role_from_groups(groups: list[str]) -> UserRole:
    """Map Cognito group membership to a UserRole.

    Group names are matched case-insensitively. If the user belongs
    to multiple groups, the highest-privilege role wins.

    Priority: ADMIN > COMPLIANCE_OFFICER > EVAL_TEAM > CLINICIAN
    """
    # Normalize group names to uppercase
    normalized = {g.upper() for g in groups}

    # Check in priority order
    if "ADMIN" in normalized or "ADMINS" in normalized:
        return UserRole.ADMIN
    if "COMPLIANCE_OFFICER" in normalized or "COMPLIANCE_OFFICERS" in normalized:
        return UserRole.COMPLIANCE_OFFICER
    if "EVAL_TEAM" in normalized or "EVAL" in normalized:
        return UserRole.EVAL_TEAM
    if "CLINICIAN" in normalized or "CLINICIANS" in normalized:
        return UserRole.CLINICIAN

    # Default to CLINICIAN if no recognized group
    logger.warning("No recognized Cognito group found in %s, defaulting to CLINICIAN", groups)
    return UserRole.CLINICIAN


def require_role(*roles: UserRole):
    """FastAPI dependency factory — require the user to have one of the specified roles."""

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user.role.value} not authorized. Required: {[r.value for r in roles]}",
            )
        return user

    return _check
