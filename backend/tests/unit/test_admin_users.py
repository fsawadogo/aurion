"""Unit tests for the persistent admin users layer (P0-06).

Covers:
- ``users_repository`` CRUD against a mocked async session.
- ``_shared.user_to_response`` mapping.
- ``_shared.resolve_clinician_names`` batch fallback for unknown ids.
- The legacy ``MOCK_USERS`` dict is gone (regression guard).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.admin import _shared
from app.api.v1.admin._shared import resolve_clinician_names, user_to_response
from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth import users_repository as users_repo


def _make_user(
    full_name: str = "Dr. Test",
    role: UserRole = UserRole.CLINICIAN,
    is_active: bool = True,
    voice_enrolled: bool = False,
) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        email=f"{full_name.lower().replace(' ', '_')}@example.com",
        password_hash="hashed",
        full_name=full_name,
        role=role,
        is_active=is_active,
        voice_enrolled=voice_enrolled,
    )
    # Populate columns that the ORM would normally fill on flush.
    from app.core.clock import utcnow
    user.created_at = utcnow()
    user.updated_at = utcnow()
    return user


def test_mock_users_dict_removed() -> None:
    """Regression guard — the in-memory MOCK_USERS dict must not return."""
    assert not hasattr(_shared, "MOCK_USERS"), (
        "MOCK_USERS dict was reintroduced — admin must read from the users table."
    )


def test_user_to_response_shape() -> None:
    user = _make_user("Dr. Perry Gdalevitch", role=UserRole.CLINICIAN, voice_enrolled=True)
    response = user_to_response(user)
    assert response.id == str(user.id)
    assert response.full_name == "Dr. Perry Gdalevitch"
    assert response.role == UserRole.CLINICIAN
    assert response.is_active is True
    assert response.voice_enrolled is True
    assert response.last_login_at is None


def test_user_to_response_handles_last_login() -> None:
    user = _make_user()
    from app.core.clock import utcnow
    user.last_login_at = utcnow()
    response = user_to_response(user)
    assert response.last_login_at is not None
    assert response.last_login_at.endswith("+00:00")


@pytest.mark.asyncio
async def test_create_user_writes_hashed_password() -> None:
    """create_user inserts a UserModel with the caller's password_hash verbatim."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    # Discard the return — assertions below inspect the model that was
    # passed to db.add(), which is the contract this test is verifying.
    await users_repo.create_user(
        db,
        email="New@Aurion.com",
        full_name="New User",
        role=UserRole.CLINICIAN,
        password_hash="$2b$12$fakehash",
    )

    assert db.add.called
    added = db.add.call_args[0][0]
    assert isinstance(added, UserModel)
    assert added.email == "new@aurion.com"  # lowercased
    assert added.password_hash == "$2b$12$fakehash"
    assert added.full_name == "New User"
    assert added.role == UserRole.CLINICIAN
    assert db.flush.await_count == 1


@pytest.mark.asyncio
async def test_update_user_records_changes() -> None:
    """update_user returns (user, changes-dict) and skips no-op fields."""
    existing = _make_user("Old Name", role=UserRole.CLINICIAN, is_active=True)

    db = MagicMock()
    db.get = AsyncMock(return_value=existing)
    db.flush = AsyncMock()

    result = await users_repo.update_user(
        db,
        existing.id,
        full_name="New Name",
        role=UserRole.ADMIN,
        is_active=True,  # no-op; should not appear in changes
    )
    assert result is not None
    user, changes = result
    assert user is existing
    assert "full_name" in changes
    assert changes["full_name"]["previous"] == "Old Name"
    assert changes["full_name"]["new"] == "New Name"
    assert "role" in changes
    assert "is_active" not in changes


@pytest.mark.asyncio
async def test_update_user_returns_none_when_missing() -> None:
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.flush = AsyncMock()

    result = await users_repo.update_user(
        db,
        uuid.uuid4(),
        full_name="anything",
    )
    assert result is None
    assert db.flush.await_count == 0


@pytest.mark.asyncio
async def test_resolve_clinician_names_falls_back_to_short_uuid() -> None:
    """Unknown ids get the 'Clinician {uuid[:8]}' shape."""
    unknown_id = uuid.UUID("12345678-1234-1234-1234-123456789012")

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))

    names = await resolve_clinician_names(db, [unknown_id])
    assert names[str(unknown_id)] == "Clinician 12345678"


@pytest.mark.asyncio
async def test_resolve_clinician_names_resolves_known_ids() -> None:
    user_id = uuid.uuid4()
    row = MagicMock()
    row.id = user_id
    row.full_name = "Dr. Perry Gdalevitch"

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: [row]))

    names = await resolve_clinician_names(db, [user_id])
    assert names[str(user_id)] == "Dr. Perry Gdalevitch"


@pytest.mark.asyncio
async def test_resolve_clinician_names_handles_empty_input() -> None:
    db = MagicMock()
    db.execute = AsyncMock()  # should not be called

    names = await resolve_clinician_names(db, [])
    assert names == {}
    assert db.execute.await_count == 0
