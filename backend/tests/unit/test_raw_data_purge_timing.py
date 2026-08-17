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

import asyncio
import traceback
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
    @pytest.mark.parametrize("deadline_exceeded", [False, True])
    async def test_run_stage1_does_not_purge_when_note_gen_fails(
        self, deadline_exceeded: bool
    ):
        """A failed Stage 1 raises before the purge — audio is kept for retry."""
        phi_sentinel = "Marie Example has a private clinical finding"
        failure = (
            tx.Stage1DeadlineExceededError()
            if deadline_exceeded
            else RuntimeError(phi_sentinel)
        )
        expected_reason = (
            "stage1_deadline_exceeded"
            if deadline_exceeded
            else "stage1_generation_failed"
        )
        expected_detail = (
            "Stage 1 processing timed out."
            if deadline_exceeded
            else "Stage 1 note generation failed."
        )
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
        transition = AsyncMock()
        alerts = AsyncMock()
        audits = AsyncMock()
        with (
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(tx, "scan_transcript_for_phi",
                         AsyncMock(return_value=MagicMock(phi_detected=False))),
            patch.object(tx, "generate_stage1_note",
                         AsyncMock(side_effect=failure)),
            patch.object(tx, "transition_session", transition),
            patch.object(tx, "try_publish_alert", alerts),
            patch.object(tx, "write_audit", audits),
            patch.object(tx, "_purge_raw_audio_if_not_retained",
                         AsyncMock()) as purge,
        ):
            with pytest.raises(tx.HTTPException) as caught:
                await tx.run_stage1(db, session, b"audio-bytes")
        purge.assert_not_awaited()
        assert caught.value.detail == expected_detail
        assert phi_sentinel not in "".join(
            traceback.format_exception(caught.value)
        )
        assert phi_sentinel not in repr(audits.await_args_list)
        assert phi_sentinel not in repr(alerts.await_args_list)
        failure_audit = next(
            call
            for call in audits.await_args_list
            if call.args[1] == tx.AuditEventType.STAGE1_FAILED
        )
        assert failure_audit.kwargs["reason"] == expected_reason
        assert alerts.await_args.kwargs["metadata"]["reason"] == expected_reason
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_stage1_owner_deadline_cancels_transcription(self):
        cancelled = asyncio.Event()

        async def blocked_transcription(*_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        db = AsyncMock()
        session = MagicMock(
            id=uuid.uuid4(),
            specialty="general",
            output_language="en",
            state=MagicMock(value="processing_stage1"),
        )
        note_gen = AsyncMock()
        audits = AsyncMock()
        with (
            patch.object(tx, "sla_stage1_ms", return_value=100),
            patch.object(
                tx,
                "transcribe_audio",
                AsyncMock(side_effect=blocked_transcription),
            ),
            patch.object(tx, "generate_stage1_note", note_gen),
            patch.object(tx, "transition_session", AsyncMock()),
            patch.object(tx, "try_publish_alert", AsyncMock()),
            patch.object(tx, "write_audit", audits),
        ):
            with pytest.raises(tx.HTTPException) as caught:
                await tx.run_stage1(db, session, b"audio-bytes")

        assert cancelled.is_set()
        assert caught.value.detail == "Stage 1 processing timed out."
        note_gen.assert_not_awaited()
        failure_audit = next(
            call
            for call in audits.await_args_list
            if call.args[1] == tx.AuditEventType.STAGE1_FAILED
        )
        assert failure_audit.kwargs["reason"] == "stage1_deadline_exceeded"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_stage1_sanitizes_ordinary_transcription_failure(self):
        phi_sentinel = "Marie Example private transcription content"
        db = AsyncMock()
        session = MagicMock(
            id=uuid.uuid4(),
            specialty="general",
            output_language="en",
            state=MagicMock(value="processing_stage1"),
        )
        note_gen = AsyncMock()
        audits = AsyncMock()
        alerts = AsyncMock()
        with (
            patch.object(
                tx,
                "transcribe_audio",
                AsyncMock(side_effect=RuntimeError(phi_sentinel)),
            ),
            patch.object(tx, "generate_stage1_note", note_gen),
            patch.object(tx, "transition_session", AsyncMock()),
            patch.object(tx, "try_publish_alert", alerts),
            patch.object(tx, "write_audit", audits),
        ):
            with pytest.raises(tx.HTTPException) as caught:
                await tx.run_stage1(db, session, b"audio-bytes")

        assert caught.value.detail == (
            "Transcription failed; the session could not be processed."
        )
        assert phi_sentinel not in "".join(
            traceback.format_exception(caught.value)
        )
        assert phi_sentinel not in repr(audits.await_args_list)
        assert phi_sentinel not in repr(alerts.await_args_list)
        note_gen.assert_not_awaited()
        failure_audit = next(
            call
            for call in audits.await_args_list
            if call.args[1] == tx.AuditEventType.STAGE1_FAILED
        )
        assert failure_audit.kwargs["reason"] == "transcription_failed"
        assert alerts.await_args.kwargs["metadata"]["reason"] == (
            "transcription_failed"
        )
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_owner_timeout_during_late_stage1_step_resets_and_fails_once(
        self,
    ):
        note, transcript = _run_stage1_env()
        late_cancelled = asyncio.Event()

        async def blocked_metric(*_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                late_cancelled.set()

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock(
            id=uuid.uuid4(),
            specialty="general",
            output_language="en",
            participants_json=None,
            template_key=None,
            custom_template_id=None,
            state=MagicMock(value="processing_stage1"),
        )
        transition = AsyncMock()
        audits = AsyncMock()
        notify = AsyncMock()
        purge = AsyncMock()
        with (
            patch.object(tx, "sla_stage1_ms", return_value=100),
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(
                tx,
                "scan_transcript_for_phi",
                AsyncMock(return_value=MagicMock(phi_detected=False)),
            ),
            patch.object(tx, "generate_stage1_note", AsyncMock(return_value=note)),
            patch.object(tx, "transition_session", transition),
            patch.object(
                tx,
                "_record_stage1_latency",
                AsyncMock(side_effect=blocked_metric),
            ),
            patch.object(tx, "notify_stage1_delivered", notify),
            patch.object(tx, "write_audit", audits),
            patch.object(tx, "try_publish_alert", AsyncMock()),
            patch.object(tx, "_purge_raw_audio_if_not_retained", purge),
        ):
            with pytest.raises(tx.HTTPException) as caught:
                await tx.run_stage1(db, session, b"audio-bytes")

        assert caught.value.detail == "Stage 1 processing timed out."
        assert late_cancelled.is_set()
        db.rollback.assert_awaited_once()
        db.refresh.assert_awaited_once_with(session)
        db.commit.assert_awaited_once()
        assert [call.args[2] for call in transition.await_args_list] == [
            tx.SessionState.AWAITING_REVIEW,
            tx.SessionState.STAGE1_FAILED,
        ]
        stage_events = [call.args[1] for call in audits.await_args_list]
        assert stage_events.count(tx.AuditEventType.STAGE1_FAILED) == 1
        assert tx.AuditEventType.STAGE1_DELIVERED not in stage_events
        notify.assert_not_awaited()
        purge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_stage1_just_within_owner_budget_succeeds(self):
        note, transcript = _run_stage1_env()
        late_step_completed = asyncio.Event()

        async def bounded_purge(*_args, **_kwargs):
            await asyncio.sleep(0.02)
            late_step_completed.set()

        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock(
            id=uuid.uuid4(),
            specialty="general",
            output_language="en",
            participants_json=None,
            template_key=None,
            custom_template_id=None,
        )
        audits = AsyncMock()
        transition = AsyncMock()
        with (
            patch.object(tx, "sla_stage1_ms", return_value=300),
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(
                tx,
                "scan_transcript_for_phi",
                AsyncMock(return_value=MagicMock(phi_detected=False)),
            ),
            patch.object(tx, "generate_stage1_note", AsyncMock(return_value=note)),
            patch.object(tx, "transition_session", transition),
            patch.object(tx, "_record_stage1_latency", AsyncMock()),
            patch.object(tx, "notify_stage1_delivered", AsyncMock()),
            patch.object(tx, "write_audit", audits),
            patch.object(
                tx,
                "_purge_raw_audio_if_not_retained",
                AsyncMock(side_effect=bounded_purge),
            ),
        ):
            result = await tx.run_stage1(db, session, b"audio-bytes")

        assert result is transcript
        assert late_step_completed.is_set()
        db.rollback.assert_not_awaited()
        db.refresh.assert_not_awaited()
        transition.assert_awaited_once_with(
            db,
            session,
            tx.SessionState.AWAITING_REVIEW,
        )
        stage_events = [call.args[1] for call in audits.await_args_list]
        assert stage_events.count(tx.AuditEventType.STAGE1_DELIVERED) == 1
        assert tx.AuditEventType.STAGE1_FAILED not in stage_events

    @pytest.mark.asyncio
    async def test_slow_post_commit_purge_cannot_flip_durable_success_to_failure(
        self,
    ):
        note, transcript = _run_stage1_env()
        purge_started = asyncio.Event()
        release_purge = asyncio.Event()
        call_order: list[str] = []

        async def commit() -> None:
            call_order.append("commit")

        async def blocked_purge(*_args, **_kwargs) -> None:
            call_order.append("purge")
            purge_started.set()
            await release_purge.wait()

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock(side_effect=commit)
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock(
            id=uuid.uuid4(),
            specialty="general",
            output_language="en",
            participants_json=None,
            template_key=None,
            custom_template_id=None,
        )
        audits = AsyncMock()
        transition = AsyncMock()
        with (
            patch.object(tx, "sla_stage1_ms", return_value=80),
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(
                tx,
                "scan_transcript_for_phi",
                AsyncMock(return_value=MagicMock(phi_detected=False)),
            ),
            patch.object(tx, "generate_stage1_note", AsyncMock(return_value=note)),
            patch.object(tx, "transition_session", transition),
            patch.object(tx, "_record_stage1_latency", AsyncMock()),
            patch.object(tx, "notify_stage1_delivered", AsyncMock()),
            patch.object(tx, "write_audit", audits),
            patch.object(
                tx,
                "_purge_raw_audio_if_not_retained",
                AsyncMock(side_effect=blocked_purge),
            ),
        ):
            result = await tx.run_stage1(db, session, b"audio-bytes")
            await purge_started.wait()

            assert result is transcript
            assert call_order == ["commit", "purge"]
            db.rollback.assert_not_awaited()
            db.refresh.assert_not_awaited()
            assert [call.args[2] for call in transition.await_args_list] == [
                tx.SessionState.AWAITING_REVIEW
            ]
            stage_events = [call.args[1] for call in audits.await_args_list]
            assert stage_events.count(tx.AuditEventType.STAGE1_DELIVERED) == 1
            assert tx.AuditEventType.STAGE1_FAILED not in stage_events

            release_purge.set()
            await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_timeout_at_commit_honors_durable_success_winner(self):
        note, transcript = _run_stage1_env()
        commit_cancelled = asyncio.Event()
        purge_finished = asyncio.Event()

        async def ambiguous_commit() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                commit_cancelled.set()

        async def refresh_as_committed(row) -> None:
            row.state = tx.SessionState.AWAITING_REVIEW

        async def purge(*_args, **_kwargs) -> None:
            purge_finished.set()

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock(side_effect=ambiguous_commit)
        db.refresh = AsyncMock(side_effect=refresh_as_committed)
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session = MagicMock(
            id=uuid.uuid4(),
            specialty="general",
            output_language="en",
            participants_json=None,
            template_key=None,
            custom_template_id=None,
            state=tx.SessionState.PROCESSING_STAGE1,
        )
        audits = AsyncMock()
        transition = AsyncMock()
        with (
            patch.object(tx, "sla_stage1_ms", return_value=80),
            patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)),
            patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)),
            patch.object(
                tx,
                "scan_transcript_for_phi",
                AsyncMock(return_value=MagicMock(phi_detected=False)),
            ),
            patch.object(tx, "generate_stage1_note", AsyncMock(return_value=note)),
            patch.object(tx, "transition_session", transition),
            patch.object(tx, "_record_stage1_latency", AsyncMock()),
            patch.object(tx, "notify_stage1_delivered", AsyncMock()),
            patch.object(tx, "write_audit", audits),
            patch.object(
                tx,
                "_purge_raw_audio_if_not_retained",
                AsyncMock(side_effect=purge),
            ),
        ):
            result = await tx.run_stage1(db, session, b"audio-bytes")
            await asyncio.wait_for(purge_finished.wait(), timeout=0.2)

        assert result is transcript
        assert commit_cancelled.is_set()
        db.rollback.assert_awaited_once()
        db.refresh.assert_awaited_once_with(session)
        assert [call.args[2] for call in transition.await_args_list] == [
            tx.SessionState.AWAITING_REVIEW
        ]
        stage_events = [call.args[1] for call in audits.await_args_list]
        assert stage_events.count(tx.AuditEventType.STAGE1_DELIVERED) == 1
        assert tx.AuditEventType.STAGE1_FAILED not in stage_events


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
