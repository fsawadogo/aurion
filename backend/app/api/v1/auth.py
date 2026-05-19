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

from app.core.clock import utcnow
from app.core.database import async_session_factory, get_db
from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth.passwords import hash_password, verify_password

logger = logging.getLogger("aurion.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_APP_ENV = os.getenv("APP_ENV", "local")

# Dev seed accounts — written to the users table on startup if absent.
class _DevUser(BaseModel):
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
    # Dedicated account for capturing the marketing demo video. Profile +
    # backlog of approved orthopedic sessions seeded via seed_demo.py.
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

    user.last_login_at = utcnow()
    await db.flush()

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
