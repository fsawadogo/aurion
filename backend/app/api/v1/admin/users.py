"""User CRUD endpoints — ADMIN only.

In-memory mock store today (``_shared.MOCK_USERS``); migrates to Cognito
+ the persistent ``users`` table when P0-06 lands.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1._helpers import write_audit
from app.api.v1.admin._shared import (
    MOCK_USERS,
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
)
from app.core.clock import utcnow
from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    """List all users. ADMIN only."""
    return list(MOCK_USERS.values())


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    """Create a new user. ADMIN only."""
    new_id = f"u{len(MOCK_USERS) + 1}_{uuid.uuid4().hex[:6]}"
    new_user = {
        "id": new_id,
        "email": body.email,
        "full_name": body.full_name,
        "role": body.role.value,
        "is_active": True,
        "voice_enrolled": False,
        "created_at": utcnow().isoformat(),
        "last_login_at": None,
    }
    MOCK_USERS[new_id] = new_user

    await write_audit(
        "system",
        "user_created",
        target_user_id=new_id,
        target_email=body.email,
        target_role=body.role,
        created_by=str(user.user_id),
    )

    return new_user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
):
    """Update user role or status. ADMIN only."""
    if user_id not in MOCK_USERS:
        raise HTTPException(status_code=404, detail="User not found")

    target = MOCK_USERS[user_id]
    changes: dict[str, Any] = {}

    if body.full_name is not None:
        changes["full_name"] = {"previous": target["full_name"], "new": body.full_name}
        target["full_name"] = body.full_name

    if body.role is not None:
        changes["role"] = {"previous": target["role"], "new": body.role.value}
        target["role"] = body.role.value

    if body.is_active is not None:
        changes["is_active"] = {"previous": target["is_active"], "new": body.is_active}
        target["is_active"] = body.is_active

    if changes:
        await write_audit(
            "system",
            "user_updated",
            target_user_id=user_id,
            changes=str(changes),
            updated_by=str(user.user_id),
        )

    return target
