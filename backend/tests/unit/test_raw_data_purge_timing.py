"""Spec-timing raw-data purge, retention-gated (#605).

The MVP Scope Definition requires raw audio deleted <1hr post-transcription
and video purged shortly post-export. The hybrid model ties the in-band
purge to the ``media_review_retention_enabled`` flag:

  * flag OFF (prod default) → spec-strict: audio purged in-band right after
    transcription; frames/clips purged on export.
  * flag ON (#338)          → keep the review/replay window; the S3 lifecycle
    TTL is the max-window backstop, so no in-band purge runs.

These tests pin: the helper's flag gate + fail-soft contract, that
``run_stage1`` invokes it only on full success, and that ``export_note_docx``
gates the frames/clips purge on the same flag.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import transcription as tx
from app.core.types import Note
from app.modules.export import service as export_service


def _flags(retention: bool) -> SimpleNamespace:
    return SimpleNamespace(
        feature_flags=SimpleNamespace(media_review_retention_enabled=retention)
    )


# ── helper: flag gate + fail-soft ───────────────────────────────────────────


class TestPurgeHelper:
    @pytest.mark.asyncio
    async def test_purges_when_retention_off(self):
        sid = uuid.uuid4()
        with (
            patch.object(tx, "get_config", return_value=_flags(False)),
            patch.object(tx, "purge_audio_for_session", AsyncMock()) as purge,
        ):
            await tx._purge_raw_audio_if_not_retained(sid)
        purge.assert_awaited_once_with(str(sid))

    @pytest.mark.asyncio
    async def test_skips_when_retention_on(self):
        with (
            patch.object(tx, "get_config", return_value=_flags(True)),
            patch.object(tx, "purge_audio_for_session", AsyncMock()) as purge,
        ):
            await tx._purge_raw_audio_if_not_retained(uuid.uuid4())
        purge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fail_soft_swallows_purge_error(self):
        # A purge hiccup must never propagate — the S3 lifecycle backstops it.
        with (
            patch.object(tx, "get_config", return_value=_flags(False)),
            patch.object(
                tx,
                "purge_audio_for_session",
                AsyncMock(side_effect=RuntimeError("s3 down")),
            ),
        ):
            await tx._purge_raw_audio_if_not_retained(uuid.uuid4())  # no raise


# ── run_stage1 wiring ───────────────────────────────────────────────────────


def _transcript() -> MagicMock:
    t = MagicMock()
    t.provider_used = "whisper"
    t.segments = [MagicMock(text="a restricted internal rotation was noted")]
    t.session_id = "s"
    t.model_dump_json.return_value = "{}"
    return t


def _run_stage1_env(note_completeness: float = 0.8):
    """Common patch set for driving run_stage1 with every collaborator mocked.
    Returns a context-manager list the test enters."""
    note = MagicMock(completeness_score=note_completeness, stage=1, version=1,
                     provider_used="anthropic")
    transcript = _transcript()
    return note, transcript


class TestRunStage1Wiring:
    @pytest.mark.asyncio
    async def test_run_stage1_purges_audio_on_success(self):
        note, transcript = _run_stage1_env()
        db = AsyncMock()
        db.add = MagicMock()  # sync in SQLAlchemy — keep it off the async path
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock(
            id=uuid.uuid4(), specialty="general", output_language="en",
            participants_json=None, template_key=None, custom_template_id=None,
        )
        with (
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(tx, "scan_transcript_for_phi",
                         AsyncMock(return_value=MagicMock(phi_detected=False))),
            patch.object(tx, "generate_stage1_note", AsyncMock(return_value=note)),
            patch.object(tx, "transition_session", AsyncMock()),
            patch.object(tx, "_record_stage1_latency", AsyncMock()),
            patch.object(tx, "notify_stage1_delivered", AsyncMock()),
            patch.object(tx, "write_audit", AsyncMock()),
            patch.object(tx, "_purge_raw_audio_if_not_retained",
                         AsyncMock()) as purge,
        ):
            await tx.run_stage1(db, session, b"audio-bytes")
        purge.assert_awaited_once_with(session.id)

    @pytest.mark.asyncio
    async def test_run_stage1_does_not_purge_when_note_gen_fails(self):
        """A failed Stage 1 raises before the purge — audio is kept for retry."""
        transcript = _transcript()
        db = AsyncMock()
        db.add = MagicMock()  # sync in SQLAlchemy — keep it off the async path
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock(
            id=uuid.uuid4(), specialty="general", output_language="en",
            participants_json=None, template_key=None, custom_template_id=None,
            state=MagicMock(value="processing_stage1"),
        )
        with (
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(tx, "scan_transcript_for_phi",
                         AsyncMock(return_value=MagicMock(phi_detected=False))),
            patch.object(tx, "generate_stage1_note",
                         AsyncMock(side_effect=RuntimeError("provider blew up"))),
            patch.object(tx, "transition_session", AsyncMock()),
            patch.object(tx, "try_publish_alert", AsyncMock()),
            patch.object(tx, "write_audit", AsyncMock()),
            patch.object(tx, "_purge_raw_audio_if_not_retained",
                         AsyncMock()) as purge,
        ):
            with pytest.raises(tx.HTTPException):
                await tx.run_stage1(db, session, b"audio-bytes")
        purge.assert_not_awaited()


# ── export_note_docx video-purge gating ─────────────────────────────────────


def _note() -> Note:
    return Note(
        session_id="s", stage=1, version=1, provider_used="anthropic",
        specialty="general", completeness_score=0.5, sections=[],
    )


class TestExportPurgeGating:
    @pytest.mark.asyncio
    async def test_export_purges_video_when_retention_off(self):
        db = AsyncMock()
        with (
            patch.object(export_service, "get_config", return_value=_flags(False)),
            patch.object(export_service, "get_audit_log_service",
                         return_value=MagicMock(write_event=AsyncMock())),
            patch.object(export_service, "migrate_eval_frames", AsyncMock()),
            patch.object(export_service, "migrate_eval_clips", AsyncMock()),
            patch.object(export_service, "purge_frames", AsyncMock()) as pf,
            patch.object(export_service, "purge_clips", AsyncMock()) as pc,
        ):
            await export_service.export_note_docx("s", _note(), db)
        pf.assert_awaited_once()
        pc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_export_keeps_video_when_retention_on(self):
        db = AsyncMock()
        with (
            patch.object(export_service, "get_config", return_value=_flags(True)),
            patch.object(export_service, "get_audit_log_service",
                         return_value=MagicMock(write_event=AsyncMock())),
            patch.object(export_service, "migrate_eval_frames", AsyncMock()) as mf,
            patch.object(export_service, "migrate_eval_clips", AsyncMock()),
            patch.object(export_service, "purge_frames", AsyncMock()) as pf,
            patch.object(export_service, "purge_clips", AsyncMock()) as pc,
        ):
            await export_service.export_note_docx("s", _note(), db)
        # Video kept for the replay window; eval migration still runs.
        pf.assert_not_awaited()
        pc.assert_not_awaited()
        mf.assert_awaited_once()
