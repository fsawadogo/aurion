"""Public waitlist / contact endpoint for the peritwin.com marketing site.

POST /api/v1/public/waitlist

The marketing site is a static export (AWS Amplify, no server of its own),
so its contact form posts here cross-origin. This is the backend's only
unauthenticated write surface, kept deliberately tiny:

  * Strict allow-listed schema (name / email / reason enum / optional
    specialty), tight length caps, ``extra="forbid"``.
  * Insert-only into ``waitlist_signups`` — no read, update, or delete is
    exposed publicly.
  * Lead PII (name, email) is never logged; log lines carry only the
    generated row id and the reason enum.
  * No clinical tables are touched and nothing here can reach PHI.

Abuse posture: the form is low-value to attackers (no auth, no reflection,
no email is sent), so validation + payload caps suffice for the pilot. If
spam appears, add a shared-secret header from the site build or CAPTCHA.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import WaitlistSignupModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])


class WaitlistSignupRequest(BaseModel):
    """Contact-form payload from the marketing site."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr = Field(max_length=320)
    reason: Literal["demo", "pilot", "partnership", "general"]
    specialty: str | None = Field(default=None, max_length=200)


class WaitlistSignupResponse(BaseModel):
    ok: bool = True


@router.post("/waitlist", response_model=WaitlistSignupResponse)
async def create_waitlist_signup(
    body: WaitlistSignupRequest,
    db: AsyncSession = Depends(get_db),
) -> WaitlistSignupResponse:
    row = WaitlistSignupModel(
        id=uuid.uuid4(),
        name=body.name.strip(),
        email=body.email.strip().lower(),
        reason=body.reason,
        specialty=body.specialty.strip() if body.specialty else None,
        source="website",
    )
    db.add(row)
    await db.commit()

    # No PII in logs — id + reason only.
    logger.info(
        "waitlist signup stored",
        extra={"signup_id": str(row.id), "reason": body.reason},
    )
    return WaitlistSignupResponse()
