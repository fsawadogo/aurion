"""User CRUD endpoints — ADMIN only.

Backed by the persistent ``users`` table via ``users_repository``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._helpers import write_audit
from app.api.v1.admin._shared import (
    UpdateUserRequest,
    UserResponse,
    user_to_response,
)
from app.api.v1.auth import generate_temp_password
from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.database import get_db
from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth import users_repository as users_repo
from app.modules.auth.passwords import hash_password
from app.modules.auth.service import CurrentUser, require_role

# Auth-events use the synthetic session UUID — same convention as the
# auth router (auth events are not session-scoped).
_AUTH_AUDIT_SESSION = uuid.UUID("00000000-0000-0000-0000-000000000000")


class CreateUserWithTempPasswordRequest(BaseModel):
    """AUTH-PIVOT-BACKEND admin-create payload. Backend generates the
    temp password; operator surfaces it via the portal Admin > Users
    page (no email)."""

    email: str
    full_name: str
    role: UserRole


class CreateUserWithTempPasswordResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    temp_password: str


class ResetPasswordResponse(BaseModel):
    user_id: str
    temp_password: str


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """List all users. ADMIN only."""
    rows = await users_repo.list_users(db)
    return [user_to_response(u) for u in rows]


@router.post(
    "/users",
    response_model=CreateUserWithTempPasswordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    body: CreateUserWithTempPasswordRequest,
    user: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user with an auto-generated temporary password.

    The temp password is returned in the response body so the
    operator can hand it to the new user out-of-band (no email is
    sent — admins control distribution). The user is forced to
    rotate it on first login by the iOS UI in a follow-up PR; the
    backend doesn't enforce a rotation cadence today, only the
    ``last_password_changed_at`` data anchor.
    """
    temp_password = generate_temp_password()
    try:
        new_user = await users_repo.create_user(
            db,
            email=body.email,
            full_name=body.full_name,
            role=body.role,
            password_hash=hash_password(temp_password),
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists.",
        )

    # USER_CREATED carries email (the historical whitelist allowed it);
    # this is the only admin-action audit event that does, and the
    # actor + target rationale is documented in audit_events.py.
    await write_audit(
        "system",
        AuditEventType.USER_CREATED,
        target_user_id=str(new_user.id),
        target_email=new_user.email,
        target_role=new_user.role.value,
        created_by=str(user.user_id),
    )
    return CreateUserWithTempPasswordResponse(
        user_id=str(new_user.id),
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role.value,
        temp_password=temp_password,
    )


@router.post(
    "/users/{user_id}/reset-password",
    response_model=ResetPasswordResponse,
)
async def admin_reset_password(
    user_id: uuid.UUID,
    actor: CurrentUser = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Rotate a user's password to a fresh temp value. ADMIN only.

    Returns the new temp password in the body so the operator can hand
    it out-of-band. Logs ADMIN_PASSWORD_RESET_ISSUED + PASSWORD_CHANGED
    (via=admin_reset) for the audit trail.
    """
    target = await db.get(UserModel, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    temp_password = generate_temp_password()
    target.password_hash = hash_password(temp_password)
    target.last_password_changed_at = utcnow()
    target.failed_login_count = 0
    target.locked_until = None

    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.ADMIN_PASSWORD_RESET_ISSUED,
        actor_id=str(actor.user_id),
        target_user_id=str(target.id),
    )
    await write_audit(
        _AUTH_AUDIT_SESSION,
        AuditEventType.PASSWORD_CHANGED,
        actor_id=str(target.id),
        via="admin_reset",
    )
    await db.flush()
    return ResetPasswordResponse(
        user_id=str(target.id), temp_password=temp_password
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
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
            AuditEventType.USER_UPDATED,
            target_user_id=user_id,
            changes=str(changes),
            updated_by=str(user.user_id),
        )
    return user_to_response(updated)
