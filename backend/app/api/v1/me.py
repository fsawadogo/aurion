"""Clinician self-scoped endpoints (``/api/v1/me/*``).

Companion to the existing ``/profile``, ``/sessions``, ``/notes`` routers.
These endpoints all act on resources owned by the calling clinician — never
on arbitrary rows — and back the web portal's clinician views.

Today this is a skeleton with the auth/role gate wired. Concrete endpoints
land in PR-B (template authoring, custom templates CRUD + upload, bulk
export, clinician-scoped audit read).

CLINICIAN role is required at the dependency layer. Admin/compliance roles
that legitimately need to look at a clinician's view can do so via the
existing ``/admin/*`` routes, which already have their own auth gates.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.types import UserRole
from app.modules.auth.service import CurrentUser, get_current_user

logger = logging.getLogger("aurion.api.me")

router = APIRouter(prefix="/me", tags=["me"])


async def get_current_clinician(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require CLINICIAN role for all ``/me/*`` endpoints.

    Admin / compliance / eval roles get 403 because the semantic of
    /me/* is "as this clinician, acting on their own data" — those
    other roles have richer admin equivalents under /admin/*.
    """
    if user.role != UserRole.CLINICIAN:
        raise HTTPException(
            status_code=403,
            detail=f"/me/* is for CLINICIAN role only (got {user.role.value})",
        )
    return user


@router.get("/_health", include_in_schema=False)
async def me_health(
    _user: CurrentUser = Depends(get_current_clinician),
) -> dict[str, str]:
    """Mounted-router liveness probe. Verifies the auth dependency works
    end-to-end (CLINICIAN sees `{ok: true}`; everyone else sees 403).
    Excluded from the public OpenAPI schema."""
    return {"ok": "true"}
