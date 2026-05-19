"""User CRUD endpoints — ADMIN only.

Backed by the persistent ``users`` table via ``users_repository``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.api.v1.admin._shared import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
    user_to_response,
)
from app.core.database import get_db
from app.core.types import UserRole
from app.modules.auth import users_repository as users_repo
from app.modules.auth.passwords import hash_password
from app.modules.auth.service import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """List all users. ADMIN only."""
    rows = await users_repo.list_users(db)
    return [user_to_response(u) for u in rows]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user. ADMIN only."""
    try:
        new_user = await users_repo.create_user(
            db,
            email=body.email,
            full_name=body.full_name,
            role=body.role,
            password_hash=hash_password(body.password),
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists.",
        )

    await write_audit(
        "system",
        "user_created",
        target_user_id=str(new_user.id),
        target_email=new_user.email,
        target_role=new_user.role.value,
        created_by=str(user.user_id),
    )
    return user_to_response(new_user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Update user role or status. ADMIN only."""
    result = await users_repo.update_user(
        db,
        user_id,
        full_name=body.full_name,
        role=body.role,
        is_active=body.is_active,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")

    updated, changes = result
    if changes:
        await write_audit(
            "system",
            "user_updated",
            target_user_id=user_id,
            changes=str(changes),
            updated_by=str(user.user_id),
        )
    return user_to_response(updated)
