"""Tests for deactivation enforcement in the auth dependency.

A user flipped to is_active=false in the DB must be blocked on their next
request even with an otherwise-valid Cognito token; a not-yet-provisioned
user (no row) passes through.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.auth.service import _ensure_active


def _db(is_active_value: object) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=is_active_value)
    db.execute = AsyncMock(return_value=result)
    return db


class TestEnsureActive:
    @pytest.mark.asyncio
    async def test_deactivated_user_is_blocked(self):
        with pytest.raises(HTTPException) as exc:
            await _ensure_active(_db(False), uuid.uuid4())
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_active_user_passes(self):
        await _ensure_active(_db(True), uuid.uuid4())  # no raise

    @pytest.mark.asyncio
    async def test_unprovisioned_user_passes(self):
        # No DB row yet (first authenticated call) → allowed through.
        await _ensure_active(_db(None), uuid.uuid4())  # no raise
