"""Shared schemas, helpers, and mock state for the admin endpoint package.

Pulled out of the original ``admin.py`` so each endpoint module (users,
audit, sessions, eval, metrics) can import what it needs without
duplicating Pydantic models or DynamoDB scan plumbing.

No business logic here — the helpers are mechanical (DynamoDB scan, JSON
parse, in-memory lookup). Each is consumed by 1-3 endpoint modules.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import UserModel
from app.core.types import UserRole
from app.modules.auth import users_repository as users_repo

# ── User schemas ───────────────────────────────────────────────────────────


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    voice_enrolled: bool
    created_at: str
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    email: str
    full_name: str
    role: UserRole
    password: str = Field(exclude=True)


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


# ── Audit schemas ──────────────────────────────────────────────────────────


class AuditEventResponse(BaseModel):
    session_id: str
    event_timestamp: str
    event_type: str
    event_id: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class PaginatedAuditResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int


# ── Masking report schemas ─────────────────────────────────────────────────


class MaskingSessionResult(BaseModel):
    """Per-session masking breakdown for the PHI masking report.

    `total_frames` is the number of masking attempts (success + failed).
    `masked_frames` counts confirmed-masked attempts. `failed_frames`
    counts on-device masking failures (P0-01 fail-closed: those bytes
    never left the device). `skipped_frames` counts frames the clinician
    explicitly skipped after a masking failure. `uploaded_frames` counts
    frames that reached the backend with a valid P0-02 masking proof.

    The session passes when no masking attempt failed and no frame was
    uploaded without proof.
    """

    session_id: str
    clinician_name: str
    date: str
    total_frames: int
    masked_frames: int
    failed_frames: int = 0
    skipped_frames: int = 0
    uploaded_frames: int = 0
    passed: bool = Field(alias="pass", serialization_alias="pass")


class MaskingReportResponse(BaseModel):
    total_sessions: int
    pass_count: int
    fail_count: int
    pass_rate: float
    sessions: list[dict[str, Any]]


# ── Pilot metrics schemas ──────────────────────────────────────────────────


class PilotMetricResponse(BaseModel):
    session_id: str
    clinician_id: str
    specialty: Optional[str] = None
    template_section_completeness: Optional[float] = None
    citation_traceability_rate: Optional[float] = None
    physician_edit_rate: Optional[float] = None
    conflict_rate: Optional[float] = None
    low_confidence_frame_rate: Optional[float] = None
    stage1_latency_ms: Optional[int] = None
    stage2_latency_ms: Optional[int] = None
    session_completeness: bool = False
    created_at: str = ""

    model_config = {"from_attributes": True}


class PaginatedMetricsResponse(BaseModel):
    items: list[PilotMetricResponse]
    total: int
    page: int
    page_size: int


# ── Admin sessions schemas ─────────────────────────────────────────────────


class SessionAdminResponse(BaseModel):
    id: str
    clinician_id: str
    clinician_name: str
    specialty: str
    state: str
    completeness_score: float
    sections_populated: int
    sections_required: int
    provider_used: str
    created_at: str
    updated_at: str


class PaginatedSessionsResponse(BaseModel):
    items: list[SessionAdminResponse]
    total: int
    page: int
    page_size: int


# ── Eval schemas ───────────────────────────────────────────────────────────


class EvalSessionResponse(BaseModel):
    id: str
    session_id: str
    clinician_name: str
    specialty: str
    transcript_masked: bool
    frames_masked: bool
    note_version: int
    scored: bool
    scores: Optional[dict[str, Any]] = None
    created_at: str


class EvalScoreRequest(BaseModel):
    transcript_accuracy: float = Field(ge=0, le=100)
    citation_correctness: float = Field(ge=0, le=100)
    descriptive_mode_compliance: float = Field(ge=0, le=100)
    notes: str = ""


# ── Config schemas ─────────────────────────────────────────────────────────


class ConfigChangeEvent(BaseModel):
    id: str
    changed_by: str
    changed_at: str
    previous_config: dict[str, Any]
    new_config: dict[str, Any]
    appconfig_version: int


# ── Helpers ────────────────────────────────────────────────────────────────


async def scan_audit_events(audit_service) -> list[dict[str, Any]]:
    """Scan all audit events from DynamoDB.

    At pilot scale (hundreds of sessions) a full table scan is acceptable.
    For production, add GSIs and use query operations.
    """
    try:
        table = audit_service._table
        response = table.scan()
        items = response.get("Items", [])

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        # Sort by timestamp descending
        items.sort(key=lambda x: x.get("event_timestamp", ""), reverse=True)
        return items
    except Exception:
        return []


def apply_audit_filters(
    events: list[dict[str, Any]],
    clinician_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    event_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Apply filters to a list of audit events."""
    filtered = events

    if clinician_id:
        filtered = [
            e for e in filtered
            if e.get("clinician_id") == clinician_id or e.get("actor_id") == clinician_id
        ]

    if date_from:
        filtered = [e for e in filtered if e.get("event_timestamp", "") >= date_from]

    if date_to:
        # Inclusive — include events up to end of the day
        to_str = date_to if "T" in date_to else f"{date_to}T23:59:59.999"
        filtered = [e for e in filtered if e.get("event_timestamp", "") <= to_str]

    if event_type:
        filtered = [e for e in filtered if e.get("event_type") == event_type]

    return filtered


def event_to_response(evt: dict[str, Any]) -> AuditEventResponse:
    """Convert a raw DynamoDB audit event to the response schema."""
    details = {
        k: v
        for k, v in evt.items()
        if k not in ("session_id", "event_timestamp", "event_type", "event_id")
    }
    return AuditEventResponse(
        session_id=evt.get("session_id", ""),
        event_timestamp=evt.get("event_timestamp", ""),
        event_type=evt.get("event_type", ""),
        event_id=evt.get("event_id", ""),
        details=details,
    )


def user_to_response(user: UserModel) -> UserResponse:
    """Map a UserModel row to the admin API response shape."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        voice_enrolled=user.voice_enrolled,
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


async def resolve_clinician_names(
    db: AsyncSession,
    clinician_ids: Iterable[Any],
) -> dict[str, str]:
    """Batch-resolve clinician UUIDs to display names.

    The returned dict is keyed by ``str(uuid)`` so callers can look up
    using the same ``str(s.clinician_id)`` they already build for
    response bodies. Unknown ids get a fallback label.
    """
    import uuid as _uuid

    uuids: list[_uuid.UUID] = []
    string_to_uuid: dict[str, _uuid.UUID] = {}
    for cid in clinician_ids:
        try:
            u = cid if isinstance(cid, _uuid.UUID) else _uuid.UUID(str(cid))
        except (ValueError, AttributeError):
            continue
        string_to_uuid[str(cid)] = u
        uuids.append(u)

    by_uuid = await users_repo.get_clinician_names(db, uuids)

    result: dict[str, str] = {}
    for raw_id, parsed in string_to_uuid.items():
        result[raw_id] = by_uuid.get(parsed, f"Clinician {raw_id[:8]}")
    return result


def safe_json_parse(value: Any) -> dict[str, Any]:
    """Safely parse a JSON string, returning empty dict on failure."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
