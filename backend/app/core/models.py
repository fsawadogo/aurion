"""SQLAlchemy ORM models for PostgreSQL tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import SessionState, UserRole


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specialty: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[SessionState] = mapped_column(
        Enum(SessionState, name="session_state"),
        nullable=False,
        default=SessionState.IDLE,
    )
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class NoteVersionModel(Base):
    __tablename__ = "note_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_used: Mapped[str] = mapped_column(String(50), nullable=False)
    specialty: Mapped[str] = mapped_column(String(50), nullable=False)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized note
    is_approved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PilotMetricsModel(Base):
    """Passive pilot behaviour metrics -- collected per session, no PHI.

    Used post-pilot to decide if/where to fine-tune models. Access
    restricted to Eval Team and CTO. Retained for ML engineer analysis.
    """

    __tablename__ = "pilot_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    specialty: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # % required sections populated (target >= 90%)
    template_section_completeness: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # % claims with valid source_id (target >= 95%)
    citation_traceability_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # JSON-encoded dict of per-section physician edit rates
    physician_edit_rate_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # % frame citations classified CONFLICTS
    conflict_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # % frames discarded due to low confidence
    low_confidence_frame_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # record_stop -> stage1_delivered (ms)
    stage1_latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # stage1_approved -> full_note_delivered (ms)
    stage2_latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # True when all 7 metrics above were logged successfully
    session_completeness: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
