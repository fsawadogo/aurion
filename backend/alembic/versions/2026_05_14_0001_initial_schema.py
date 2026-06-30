"""initial schema

Captures the 8 tables that ``Base.metadata.create_all`` was producing on
startup prior to alembic ownership: users, sessions, physician_profiles,
transcripts, note_versions, custom_templates, pilot_metrics, stage2_jobs.

Two PG enums (user_role, session_state) are created up-front so the
column-level ENUM(create_type=False) references resolve.

Revision ID: 0001
Revises:
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


USER_ROLE_VALUES = (
    "CLINICIAN",
    "EVAL_TEAM",
    "COMPLIANCE_OFFICER",
    "ADMIN",
    # CLINICAL_ADMIN (#578) — in the baseline so a fresh DB creates the enum
    # complete; migration 0044 ADD VALUE IF NOT EXISTS covers existing DBs.
    "CLINICAL_ADMIN",
)
SESSION_STATE_VALUES = (
    "IDLE",
    "CONSENT_PENDING",
    "RECORDING",
    "PAUSED",
    "PROCESSING_STAGE1",
    "AWAITING_REVIEW",
    "PROCESSING_STAGE2",
    "REVIEW_COMPLETE",
    "EXPORTED",
    "PURGED",
    # Added by migration 0030 (lane-backend/empty-transcript-guard).
    # Kept in lockstep with app.core.types.SessionState — see
    # tests/integration/test_migrations.py::test_baseline_enums_match_python_enums.
    "STAGE1_FAILED_NO_AUDIO",
    # Added by migration 0043 (lane-backend/stage1-failed-enum). Generic Stage 1
    # failure (provider parse error / rate limit / timeout) — distinct from the
    # NO_AUDIO case (empty transcript, provider never called).
    "STAGE1_FAILED",
)


def upgrade() -> None:
    user_role = postgresql.ENUM(*USER_ROLE_VALUES, name="user_role")
    session_state = postgresql.ENUM(*SESSION_STATE_VALUES, name="session_state")
    user_role.create(op.get_bind(), checkfirst=True)
    session_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(*USER_ROLE_VALUES, name="user_role", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("clinician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialty", sa.String(50), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(*SESSION_STATE_VALUES, name="session_state", create_type=False),
            nullable=False,
        ),
        sa.Column("consultation_type", sa.String(50), nullable=True),
        sa.Column("encounter_context", sa.Text, nullable=True),
        sa.Column("output_language", sa.String(10), nullable=False),
        sa.Column("encounter_type", sa.String(50), nullable=False),
        sa.Column("participants_json", sa.Text, nullable=True),
        sa.Column("capture_mode", sa.String(20), nullable=False),
        sa.Column("consent_confirmed", sa.Boolean, nullable=False),
        sa.Column("provider_overrides", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "physician_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinician_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("practice_type", sa.String(50), nullable=True),
        sa.Column("primary_specialty", sa.String(50), nullable=False),
        sa.Column("preferred_templates", sa.Text, nullable=False),
        sa.Column("consultation_types", sa.Text, nullable=False),
        sa.Column("allied_health_team", sa.Text, nullable=False),
        sa.Column("output_language", sa.String(10), nullable=False),
        sa.Column("auto_upload", sa.Boolean, nullable=False),
        sa.Column("retention_days", sa.Integer, nullable=False),
        sa.Column("consent_reprompt", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_physician_profiles_clinician_id",
        "physician_profiles",
        ["clinician_id"],
        unique=True,
    )

    op.create_table(
        "transcripts",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_used", sa.String(50), nullable=False),
        sa.Column("transcript_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "note_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("stage", sa.Integer, nullable=False),
        sa.Column("provider_used", sa.String(50), nullable=False),
        sa.Column("specialty", sa.String(50), nullable=False),
        sa.Column("completeness_score", sa.Float, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("is_approved", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_note_versions_session_id",
        "note_versions",
        ["session_id"],
    )

    op.create_table(
        "custom_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_shared", sa.Boolean, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "pilot_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialty", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("template_section_completeness", sa.Float, nullable=True),
        sa.Column("citation_traceability_rate", sa.Float, nullable=True),
        sa.Column("physician_edit_rate_json", sa.Text, nullable=True),
        sa.Column("conflict_rate", sa.Float, nullable=True),
        sa.Column("low_confidence_frame_rate", sa.Float, nullable=True),
        sa.Column("stage1_latency_ms", sa.Integer, nullable=True),
        sa.Column("stage2_latency_ms", sa.Integer, nullable=True),
        sa.Column("session_completeness", sa.Boolean, nullable=False),
    )
    op.create_index(
        "ix_pilot_metrics_session_id",
        "pilot_metrics",
        ["session_id"],
    )

    op.create_table(
        "stage2_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_note_version", sa.Integer, nullable=True),
        sa.Column("frames_processed", sa.Integer, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_stage2_jobs_session_id",
        "stage2_jobs",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stage2_jobs_session_id", table_name="stage2_jobs")
    op.drop_table("stage2_jobs")
    op.drop_index("ix_pilot_metrics_session_id", table_name="pilot_metrics")
    op.drop_table("pilot_metrics")
    op.drop_table("custom_templates")
    op.drop_index("ix_note_versions_session_id", table_name="note_versions")
    op.drop_table("note_versions")
    op.drop_table("transcripts")
    op.drop_index(
        "ix_physician_profiles_clinician_id",
        table_name="physician_profiles",
    )
    op.drop_table("physician_profiles")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    postgresql.ENUM(name="session_state").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_role").drop(op.get_bind(), checkfirst=True)
