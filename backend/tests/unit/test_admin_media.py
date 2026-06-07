"""Unit tests for the admin Captured Media endpoints (#338).

Exercises the route coroutines directly with mocked DB / S3 / audit
collaborators (same pattern as ``test_feature_flags_admin.py``):

  - Flag gate: 403 when ``media_review_retention_enabled`` is off.
  - List: media-bearing + windowed rows map to PHI-free items with the
    physician name, visit/context/encounter fields, and a retention
    countdown; availability comes from a bounded S3 list.
  - Download: ADMIN/EVAL only; presigned URLs + an EVIDENCE_DOWNLOADED
    audit row carrying count-only kwargs (never an S3 key / URL); per-entry
    presign failures degrade rather than 500.
  - Role gate: COMPLIANCE_OFFICER blocked from download, CLINICIAN blocked
    everywhere.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.api.v1.admin import media as media_module
from app.api.v1.admin.media import (
    _clip_id_from_key,
    _expires_at,
    _media_availability,
    _resolve_download_urls,
    get_media_download_urls,
    list_captured_media,
)
from app.core.audit_events import AuditEventType
from app.core.models import SessionModel
from app.core.types import SessionState, UserRole
from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig

_MEDIA = "app.api.v1.admin.media"


# ── Fixtures / builders ──────────────────────────────────────────────────────


def _config(*, retention: bool, days: int = 7) -> AppConfigSchema:
    cfg = AppConfigSchema(
        feature_flags=FeatureFlagsConfig(media_review_retention_enabled=retention)
    )
    cfg.pipeline.media_review_retention_days = days
    return cfg


def _user(role: UserRole) -> MagicMock:
    return MagicMock(role=role, user_id=uuid.uuid4(), email="x@aurion.local")


def _session(
    *,
    state: SessionState = SessionState.AWAITING_REVIEW,
    consultation_type: str | None = "follow_up",
    encounter_context: str | None = "LL follow-up",
    encounter_type: str = "doctor_patient",
) -> SessionModel:
    return SessionModel(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        specialty="orthopedic_surgery",
        state=state,
        consultation_type=consultation_type,
        encounter_context=encounter_context,
        encounter_type=encounter_type,
        created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


def _s3_client(*, audio_keys: list[str], clip_keys: list[str], truncated: bool = False):
    """Mock S3 client whose list_objects_v2 keys off the prefix."""
    client = MagicMock()

    def _list(*, Bucket, Prefix, MaxKeys=None):  # noqa: N803 (boto kwargs)
        if Prefix.startswith("audio/"):
            keys = audio_keys
        elif Prefix.startswith("clips/"):
            keys = clip_keys
        else:
            keys = []
        return {
            "Contents": [{"Key": k} for k in keys],
            "IsTruncated": truncated,
        }

    client.list_objects_v2 = MagicMock(side_effect=_list)
    return client


def _mock_db(sessions: list[SessionModel]) -> MagicMock:
    """A DB whose execute() returns a count then a page of sessions."""
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = len(sessions)
    page_result = MagicMock()
    page_result.scalars.return_value.all.return_value = sessions
    db.execute = AsyncMock(side_effect=[count_result, page_result])
    return db


# ── Pure helpers ─────────────────────────────────────────────────────────────


class TestPureHelpers:
    def test_clip_id_strips_prefix_and_extension(self) -> None:
        key = "clips/2b1c.../clip_00042.mp4"
        assert _clip_id_from_key(key) == "clip_00042"

    def test_clip_id_without_extension(self) -> None:
        assert _clip_id_from_key("clips/x/raw_object") == "raw_object"

    def test_expires_at_adds_window(self) -> None:
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        out = _expires_at(start, 7)
        assert out.startswith("2026-06-08")

    def test_expires_at_none_started_is_empty(self) -> None:
        assert _expires_at(None, 7) == ""

    def test_media_availability_counts(self) -> None:
        client = _s3_client(
            audio_keys=["audio/s/a.wav"], clip_keys=["clips/s/1.mp4", "clips/s/2.mp4"]
        )
        with patch(f"{_MEDIA}.get_s3_client", return_value=client):
            has_audio, clip_count = _media_availability("s")
        assert has_audio is True
        assert clip_count == 2

    def test_media_availability_no_media(self) -> None:
        client = _s3_client(audio_keys=[], clip_keys=[])
        with patch(f"{_MEDIA}.get_s3_client", return_value=client):
            has_audio, clip_count = _media_availability("s")
        assert has_audio is False
        assert clip_count == 0


# ── Flag gate ────────────────────────────────────────────────────────────────


class TestFlagGate:
    @pytest.mark.asyncio
    async def test_list_flag_off_returns_403(self) -> None:
        with patch(f"{_MEDIA}.get_config", return_value=_config(retention=False)):
            with pytest.raises(HTTPException) as exc:
                await list_captured_media(
                    page=1, page_size=50, user=_user(UserRole.ADMIN), db=MagicMock()
                )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_download_flag_off_returns_403(self) -> None:
        with patch(f"{_MEDIA}.get_config", return_value=_config(retention=False)):
            with pytest.raises(HTTPException) as exc:
                await get_media_download_urls(
                    session_id=str(uuid.uuid4()),
                    user=_user(UserRole.ADMIN),
                    db=MagicMock(),
                )
        assert exc.value.status_code == 403


# ── GET /admin/media ─────────────────────────────────────────────────────────


class TestListCapturedMedia:
    @pytest.mark.asyncio
    async def test_list_maps_phi_free_item(self) -> None:
        session = _session()
        db = _mock_db([session])
        client = _s3_client(
            audio_keys=[f"audio/{session.id}/a.wav"],
            clip_keys=[f"clips/{session.id}/c1.mp4"],
        )
        with (
            patch(f"{_MEDIA}.get_config", return_value=_config(retention=True, days=7)),
            patch(
                f"{_MEDIA}.resolve_clinician_names",
                new=AsyncMock(return_value={str(session.clinician_id): "Dr. Perry G."}),
            ),
            patch(f"{_MEDIA}.get_s3_client", return_value=client),
        ):
            resp = await list_captured_media(
                page=1, page_size=50, user=_user(UserRole.EVAL_TEAM), db=db
            )

        assert resp.total == 1
        assert resp.retention_days == 7
        assert len(resp.items) == 1
        item = resp.items[0]
        assert item.session_id == str(session.id)
        assert item.physician_name == "Dr. Perry G."
        assert item.visit_type == "follow_up"
        assert item.context_label == "LL follow-up"
        assert item.encounter_type == "doctor_patient"
        assert item.state == "AWAITING_REVIEW"
        assert item.has_audio is True
        assert item.clip_count == 1
        # Retention countdown = created_at + 7 days.
        assert item.retention_expires_at.startswith("2026-06-08")
        # NO patient identifier on the wire.
        dumped = item.model_dump()
        for forbidden in (
            "external_reference_id",
            "patient_id",
            "patient_name",
            "identifier",
        ):
            assert forbidden not in dumped

    @pytest.mark.asyncio
    async def test_list_reports_purged_session_as_unavailable(self) -> None:
        """A session still in-window but whose media was already removed
        shows has_audio=false / clip_count=0 rather than being hidden."""
        session = _session(state=SessionState.EXPORTED)
        db = _mock_db([session])
        client = _s3_client(audio_keys=[], clip_keys=[])
        with (
            patch(f"{_MEDIA}.get_config", return_value=_config(retention=True)),
            patch(
                f"{_MEDIA}.resolve_clinician_names",
                new=AsyncMock(return_value={str(session.clinician_id): "Dr. X"}),
            ),
            patch(f"{_MEDIA}.get_s3_client", return_value=client),
        ):
            resp = await list_captured_media(
                page=1, page_size=50, user=_user(UserRole.COMPLIANCE_OFFICER), db=db
            )
        assert resp.items[0].has_audio is False
        assert resp.items[0].clip_count == 0


# ── GET /admin/media/{id}/download-urls ──────────────────────────────────────


class TestDownloadUrls:
    @pytest.mark.asyncio
    async def test_download_returns_urls_and_audits_counts(self) -> None:
        session = _session()
        client = _s3_client(
            audio_keys=[f"audio/{session.id}/a.wav"],
            clip_keys=[f"clips/{session.id}/clip_1.mp4", f"clips/{session.id}/clip_2.mp4"],
        )
        user = _user(UserRole.ADMIN)
        audit_mock = AsyncMock()
        with (
            patch(f"{_MEDIA}.get_config", return_value=_config(retention=True)),
            patch(
                f"{_MEDIA}.get_session_or_404",
                new=AsyncMock(return_value=session),
            ),
            patch(f"{_MEDIA}.get_s3_client", return_value=client),
            patch(
                f"{_MEDIA}.generate_presigned_evidence_url",
                side_effect=lambda key, bucket=None: f"https://signed/{key}",
            ),
            patch(f"{_MEDIA}.write_audit", new=audit_mock),
        ):
            resp = await get_media_download_urls(
                session_id=str(session.id), user=user, db=MagicMock()
            )

        assert resp.audio_url == f"https://signed/audio/{session.id}/a.wav"
        assert [c.clip_id for c in resp.clips] == ["clip_1", "clip_2"]
        assert resp.expires_in == 3600

        # Audit emitted with PHI-free counts only — never a key / URL.
        audit_mock.assert_awaited_once()
        args, kwargs = audit_mock.await_args
        assert args[0] == session.id
        assert args[1] == AuditEventType.EVIDENCE_DOWNLOADED
        assert kwargs["actor_id"] == str(user.user_id)
        assert kwargs["evidence_kind"] == "session_media"
        assert kwargs["audio_count"] == 1
        assert kwargs["clip_count"] == 2
        assert "s3_key" not in kwargs
        assert "audio_url" not in kwargs
        assert "url" not in kwargs

    @pytest.mark.asyncio
    async def test_download_degrades_on_presign_error(self) -> None:
        """A presign error degrades that entry (audio null / clip skipped)
        rather than 500ing the whole call; the audit still fires."""
        session = _session()
        client = _s3_client(
            audio_keys=[f"audio/{session.id}/a.wav"],
            clip_keys=[f"clips/{session.id}/c.mp4"],
        )
        err = ClientError({"Error": {"Code": "X"}}, "GetObject")
        audit_mock = AsyncMock()
        with (
            patch(f"{_MEDIA}.get_config", return_value=_config(retention=True)),
            patch(
                f"{_MEDIA}.get_session_or_404",
                new=AsyncMock(return_value=session),
            ),
            patch(f"{_MEDIA}.get_s3_client", return_value=client),
            patch(f"{_MEDIA}.generate_presigned_evidence_url", side_effect=err),
            patch(f"{_MEDIA}.write_audit", new=audit_mock),
        ):
            resp = await get_media_download_urls(
                session_id=str(session.id), user=_user(UserRole.EVAL_TEAM), db=MagicMock()
            )

        assert resp.audio_url is None
        assert resp.clips == []
        # Counts reflect what existed (audit is about access intent), even
        # though presigning degraded.
        audit_mock.assert_awaited_once()
        assert audit_mock.await_args.kwargs["audio_count"] == 1
        assert audit_mock.await_args.kwargs["clip_count"] == 1

    def test_resolve_download_urls_counts_independent_of_presign(self) -> None:
        client = _s3_client(audio_keys=["audio/s/a.wav"], clip_keys=["clips/s/c.mp4"])
        with (
            patch(f"{_MEDIA}.get_s3_client", return_value=client),
            patch(
                f"{_MEDIA}.generate_presigned_evidence_url",
                side_effect=lambda key, bucket=None: f"u:{key}",
            ),
        ):
            audio_url, clips, audio_count, clip_count = _resolve_download_urls("s")
        assert audio_count == 1
        assert clip_count == 1
        assert audio_url == "u:audio/s/a.wav"
        assert len(clips) == 1


# ── Role gate ────────────────────────────────────────────────────────────────


class TestRoleGate:
    @pytest.mark.asyncio
    async def test_download_blocks_compliance_officer(self) -> None:
        """COMPLIANCE_OFFICER is view-only — the download gate is
        require_role(ADMIN, EVAL_TEAM), so compliance gets a 403."""
        from app.modules.auth.service import require_role

        check = require_role(UserRole.ADMIN, UserRole.EVAL_TEAM)
        with pytest.raises(HTTPException) as exc:
            await check(user=_user(UserRole.COMPLIANCE_OFFICER))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_allows_compliance_blocks_clinician(self) -> None:
        from app.modules.auth.service import require_role

        check = require_role(
            UserRole.ADMIN, UserRole.EVAL_TEAM, UserRole.COMPLIANCE_OFFICER
        )
        # Compliance allowed through.
        assert await check(user=_user(UserRole.COMPLIANCE_OFFICER)) is not None
        # Clinician blocked.
        with pytest.raises(HTTPException) as exc:
            await check(user=_user(UserRole.CLINICIAN))
        assert exc.value.status_code == 403

    def test_route_role_gates_in_source(self) -> None:
        """Belt-and-braces: the list gate names all three roles; the
        download gate names only ADMIN + EVAL_TEAM (no compliance)."""
        with open(media_module.__file__) as f:
            text = f.read()
        assert "UserRole.COMPLIANCE_OFFICER" in text  # list gate includes it
        # The download gate must be ADMIN + EVAL_TEAM only.
        assert "require_role(UserRole.ADMIN, UserRole.EVAL_TEAM)" in text
