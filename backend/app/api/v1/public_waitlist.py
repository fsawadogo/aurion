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

Abuse posture: the form is low-value to attackers (no auth, no content
reflection back to the submitter), so validation + payload caps suffice for
the pilot. The team-notification email HTML-escapes every lead-supplied
value. If spam appears, add a shared-secret header from the site build or
CAPTCHA.
"""

from __future__ import annotations

import html
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.email_sender import EmailSendError, send_email
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

    # Best-effort notification to the team inbox. The signup is already
    # committed — a mail-transport failure must never bounce the form, so
    # errors are swallowed after a redacted warning. Lead PII may appear in
    # the EMAIL body (that's its job), never in logs.
    await _notify_team(row)

    return WaitlistSignupResponse()


async def _notify_team(row: WaitlistSignupModel) -> None:
    notify_to = os.getenv("WAITLIST_NOTIFY_EMAIL", "").strip()
    if not notify_to:
        return

    from_address = os.getenv(
        "WAITLIST_EMAIL_FROM",
        os.getenv("AUTH_EMAIL_FROM", "noreply@aurionclinical.com"),
    )
    lines = [
        f"Name:      {row.name}",
        f"Email:     {row.email}",
        f"Reason:    {row.reason}",
        f"Specialty: {row.specialty or '—'}",
        f"Signup id: {row.id}",
    ]
    text_body = "New contact from peritwin.com\n\n" + "\n".join(lines)
    html_rows = "".join(
        f"<tr><td style='padding:2px 12px 2px 0;color:#6b7280'>{label}</td>"
        f"<td style='padding:2px 0'><strong>{html.escape(str(value))}</strong></td></tr>"
        for label, value in [
            ("Name", row.name),
            ("Email", row.email),
            ("Reason", row.reason),
            ("Specialty", row.specialty or "—"),
            ("Signup id", str(row.id)),
        ]
    )
    html_body = (
        "<p>New contact from <strong>peritwin.com</strong></p>"
        f"<table style='font-family:sans-serif;font-size:14px'>{html_rows}</table>"
    )

    try:
        await send_email(
            to=notify_to,
            subject=f"PeriTwin contact — {row.reason}",
            text_body=text_body,
            html_body=html_body,
            from_address=from_address,
        )
        logger.info(
            "waitlist notification dispatched",
            extra={"signup_id": str(row.id)},
        )
    except EmailSendError:
        logger.warning(
            "waitlist notification email failed",
            extra={"signup_id": str(row.id)},
        )
