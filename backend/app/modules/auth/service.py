"""JWT authentication and role-based authorization.

Validates JWT tokens issued by AWS Cognito. In local dev, accepts
a simple bearer token with role claim for testing.
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
from jose.utils import base64url_decode

from app.core.types import UserRole

logger = logging.getLogger("aurion.auth")

_security = HTTPBearer()
_APP_ENV = os.getenv("APP_ENV", "local")

# ── Cognito Configuration ────────────────────────────────────────────────

_COGNITO_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
_COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")

# JWKS cache: store the keys and a timestamp for cache invalidation
_jwks_cache: Optional[dict[str, Any]] = None
_jwks_cache_timestamp: float = 0.0
_JWKS_CACHE_TTL_SECONDS = 86400  # 24 hours


class CurrentUser:
    """Represents the authenticated user extracted from JWT."""

    def __init__(self, user_id: uuid.UUID, role: UserRole, email: str = ""):
        self.user_id = user_id
        self.role = role
        self.email = email


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> CurrentUser:
    """FastAPI dependency — extract and validate the current user from JWT.

    In local dev, accepts a simple token format: <role>:<user_id>
    In production, validates against Cognito JWKS.
    """
    token = credentials.credentials

    if _APP_ENV == "local":
        return _parse_dev_token(token)

    # Production: validate JWT against Cognito JWKS
    return await _validate_cognito_jwt(token)


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
