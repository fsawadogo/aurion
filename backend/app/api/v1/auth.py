"""Auth API routes — register + dev-mode login against the users table.

Production deployments still front auth with Cognito hosted UI; the
endpoints below are for local development and the pilot's bootstrapping
phase. The dev token format `<role>:<user_id>` is preserved so the
`auth.service` JWT path doesn't have to change.
"""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, get_db
from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth.passwords import hash_password, verify_password

logger = logging.getLogger("aurion.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_APP_ENV = os.getenv("APP_ENV", "local")

# Dev seed accounts — written to the users table on startup if absent.
# (password, user_id, full_name, role)
_DEV_USERS: dict[str, tuple[str, str, str, UserRole]] = {
    "admin@aurionclinical.com": ("admin", "00000000-0000-0000-0000-000000000000", "Admin", UserRole.ADMIN),
    "perry@creoq.ca": ("perry", "00000000-0000-0000-0000-000000000001", "Dr. Perry Gdalevitch", UserRole.CLINICIAN),
    "marie@creoq.ca": ("marie", "00000000-0000-0000-0000-000000000002", "Dr. Marie Gdalevitch", UserRole.CLINICIAN),
    "compliance@aurionclinical.com": ("compliance", "00000000-0000-0000-0000-000000000003", "Compliance Officer", UserRole.COMPLIANCE_OFFICER),
    "eval@aurionclinical.com": ("eval", "00000000-0000-0000-0000-000000000004", "Eval Reviewer", UserRole.EVAL_TEAM),
}


# ── Schemas ─────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    full_name: str


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """Authenticate against the users table. Dev-only outside production Cognito."""
    if _APP_ENV != "local":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev login disabled in production. Use Cognito hosted UI.",
        )

    user = await _find_user_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    return _build_login_response(user)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """Create a CLINICIAN account and return a session token.

    Higher-privilege roles (ADMIN, COMPLIANCE_OFFICER, EVAL_TEAM) are not
    self-serve — operators provision them by updating the role column.
    """
    if _APP_ENV != "local":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Self-serve registration disabled in production. Use Cognito hosted UI.",
        )

    user = UserModel(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip(),
        role=UserRole.CLINICIAN,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    logger.info("New user registered: id=%s role=%s", user.id, user.role.value)
    return _build_login_response(user)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _build_login_response(user: UserModel) -> LoginResponse:
    """Same dev token format the auth service has always parsed."""
    token = f"{user.role.value}:{user.id}"
    return LoginResponse(
        access_token=token,
        role=user.role.value,
        user_id=str(user.id),
        full_name=user.full_name,
    )


async def _find_user_by_email(db: AsyncSession, email: str) -> UserModel | None:
    result = await db.execute(select(UserModel).where(UserModel.email == email.lower()))
    return result.scalar_one_or_none()


async def seed_dev_users() -> None:
    """Idempotent — inserts the 5 seed accounts if their emails are missing.

    Called from main.lifespan on startup so existing dev tokens (`ROLE:UUID`)
    keep resolving to the same user IDs the iOS client may have cached.
    """
    if _APP_ENV != "local":
        return

    async with async_session_factory() as db:
        for email, (password, user_id, full_name, role) in _DEV_USERS.items():
            existing = await _find_user_by_email(db, email)
            if existing is not None:
                continue
            db.add(
                UserModel(
                    id=uuid.UUID(user_id),
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=role,
                )
            )
        await db.commit()
