"""JWT authentication and role-based authorization.

Validates JWT tokens issued by AWS Cognito. In local dev, accepts
a simple bearer token with role claim for testing.
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.types import UserRole

_security = HTTPBearer()
_APP_ENV = os.getenv("APP_ENV", "local")


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
    # Will be implemented when Cognito is provisioned
    return _validate_cognito_jwt(token)


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


def _validate_cognito_jwt(token: str) -> CurrentUser:
    """Validate JWT against Cognito JWKS. Placeholder for Phase 8."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Cognito JWT validation not yet implemented. Set APP_ENV=local for dev tokens.",
    )


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
